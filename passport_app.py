import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import os
import glob
from PIL import Image
from google.oauth2.service_account import Credentials
from google.cloud import vision
import io
import pillow_heif
import importlib
from datetime import datetime, timedelta
import pandas as pd

# Register HEIC opener
pillow_heif.register_heif_opener()

from pdf2image import convert_from_bytes

# Custom modules
import ocr_utils
importlib.reload(ocr_utils)
import excel_utils
importlib.reload(excel_utils)
import bcrypt

# Page Config
st.set_page_config(page_title="パスポートOCRシステム", layout="wide")

def load_auth_config():
    # 1. Try Streamlit Secrets (for Cloud)
    # Streamlit Secrets handles TOML automatically and exposes it as a dict-like object
    # We expect the structure to match what Authenticator expects.
    if "credentials" in st.secrets:
        try:
            # Deep conversion to dict if necessary, or just return keys
            # Secrets might be locked, so we convert to a mutable dict for usage
            config = {
                'credentials': dict(st.secrets['credentials']),
                'cookie': dict(st.secrets['cookie']),
                'preauthorized': dict(st.secrets.get('preauthorized', {'emails': []}))
            }
            # Adjust nested 'usernames' dict inside credentials if it's AttrDict
            if 'usernames' in config['credentials']:
                config['credentials']['usernames'] = dict(config['credentials']['usernames'])
                for user, details in config['credentials']['usernames'].items():
                     config['credentials']['usernames'][user] = dict(details)
                     
            return config
        except Exception as e:
            st.error(f"Secretsからの設定読み込みエラー: {e}")
            return None

    # 2. Try Local File (for Local Dev)
    auth_file = "auth_config.yaml"
    if not os.path.exists(auth_file):
        st.error(f"{auth_file} が見つかりません。")
        return None
    with open(auth_file) as file:
        config = yaml.load(file, Loader=SafeLoader)
    return config

config = load_auth_config()

if config:
    authenticator = stauth.Authenticate(
        config['credentials'],
        config['cookie']['name'],
        config['cookie']['key'],
        config['cookie']['expiry_days']
    )

    authenticator.login(location='main')

    if st.session_state["authentication_status"] is False:
        st.error('ユーザー名またはパスワードが間違っています')
    elif st.session_state["authentication_status"] is None:
        st.warning('ログインしてください')
    elif st.session_state["authentication_status"]:
        # --- LOGGED IN ---
        username = st.session_state["username"]
        name = st.session_state["name"]
        
        st.sidebar.write(f'Welcome *{name}*')
        authenticator.logout(location='sidebar')
        
        # --- ADMIN SECTION ---
        if username == 'admin':
            st.sidebar.markdown("---")
            with st.sidebar.expander("👥 ユーザー管理 (Admin)", expanded=False):
                # 1. User List
                current_users = list(config['credentials']['usernames'].keys())
                st.write(f"登録ユーザー数: {len(current_users)}")
                st.code("\n".join(current_users))
                
                st.markdown("---")
                
                # 2. Add User
                st.subheader("ユーザー追加")
                with st.form("add_user_form", clear_on_submit=True):
                    new_user = st.text_input("ユーザーID (英数字)")
                    new_name = st.text_input("表示名")
                    new_pass = st.text_input("パスワード", type="password")
                    submitted = st.form_submit_button("追加")
                    
                    if submitted:
                        if new_user and new_name and new_pass:
                            if new_user in config['credentials']['usernames']:
                                st.error("そのIDは既に存在します")
                            else:
                                # Hash Password
                                hashed = bcrypt.hashpw(new_pass.encode(), bcrypt.gensalt()).decode()
                                
                                # Update Config Dict
                                config['credentials']['usernames'][new_user] = {
                                    'email': f"{new_user}@example.com", # Dummy or input
                                    'name': new_name,
                                    'password': hashed,
                                    'logged_in': False,
                                    'data_dir': f"./data/{new_user}"
                                }
                                
                                # Save to YAML
                                with open('auth_config.yaml', 'w') as f:
                                    yaml.dump(config, f, default_flow_style=False)
                                
                                st.success(f"ユーザー '{new_user}' を追加しました")
                                st.rerun() # Refresh list
                        else:
                            st.error("全項目を入力してください")

                st.markdown("---")
                
                # 3. Delete User
                st.subheader("ユーザー削除")
                del_target = st.selectbox("削除対象", ["-"] + [u for u in current_users if u != 'admin'])
                if st.button("削除実行"):
                    if del_target != "-":
                       del config['credentials']['usernames'][del_target]
                       # Save
                       with open('auth_config.yaml', 'w') as f:
                            yaml.dump(config, f, default_flow_style=False)
                       st.success(f"'{del_target}' を削除しました")
                       st.rerun()

        # User Data Directory Setup
        if 'data_dir' in config['credentials']['usernames'][username]:
            user_data_dir = config['credentials']['usernames'][username]['data_dir']
        else:
            user_data_dir = f"./data/{username}"
            
        os.makedirs(user_data_dir, exist_ok=True)
        excel_path = os.path.join(user_data_dir, "passport_list.xlsx")
        
        st.title("🇯🇵 パスポートOCR転記システム")
        
        # --- GCP Credentials Setup ---
        # ユーザーごとの設定ではなく、システム共通のサービスアカウントを使う
        # res_card_ocrからコピーした service_account.json を参照
        # --- GCP Credentials Setup ---
        # ユーザーごとの設定ではなく、システム共通のサービスアカウントを使う
        # ローカルでは service_account.json を参照
        # クラウド(Streamlit Cloud等)では st.secrets["gcp_service_account"] を参照
        SERVICE_ACCOUNT_FILE = "service_account.json"
        
        def get_vision_client():
            # 1. Try Local File
            if os.path.exists(SERVICE_ACCOUNT_FILE):
                creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
                return vision.ImageAnnotatorClient(credentials=creds)
            
            # 2. Try Streamlit Secrets
            elif "gcp_service_account" in st.secrets:
                try:
                    # st.secrets returns a AttrDict, transform to normal dict for from_service_account_info
                    info = dict(st.secrets["gcp_service_account"])
                    creds = Credentials.from_service_account_info(info)
                    return vision.ImageAnnotatorClient(credentials=creds)
                except Exception as e:
                     st.error(f"Secretsからの認証に失敗しました: {e}")
                     return None
            else:
                st.error("GCP認証情報が見つかりません。(service_account.json または st.secrets)")
                return None

        vision_client = get_vision_client()
        
        # --- Tabs ---
        tab1, tab2, tab3 = st.tabs(["📷 単票読み取り", "📂 一括読み取り (フォルダ指定)", "📊 データ管理"])
        
        # ==========================================
        # TAB 1: Single Scan
        # ==========================================
        with tab1:
            st.header("1枚ずつ読み取り・登録")
            
            uploaded_file = st.file_uploader("パスポート画像をアップロード", type=['png', 'jpg', 'jpeg', 'heic', 'pdf'], key='single_uploader')
            
            if uploaded_file:
                # Handle HEIC or standard image or PDF
                try:
                    if uploaded_file.name.lower().endswith('.heic'):
                        image = Image.open(uploaded_file)
                    elif uploaded_file.name.lower().endswith('.pdf'):
                        # Convert PDF first page to image
                        pages = convert_from_bytes(uploaded_file.read())
                        if pages:
                            image = pages[0]
                        else:
                            st.error("PDFページが見つかりませんでした。")
                            image = None
                    else:
                        image = Image.open(uploaded_file)
                        
                    if image:
                        st.image(image, caption="アップロード画像", use_container_width=True)
                except Exception as e:
                    st.error(f"ファイルを開けませんでした: {e}")
                    image = None
                
                # Options - Removed FAX mode as per request
                # use_fax_mode = st.checkbox("低画質・FAXモード...", ...)

                if image and st.button("OCR解析開始", key='btn_single_ocr'):
                    if not vision_client:
                        st.error("OCRエンジンの初期化に失敗しました。")
                    else:
                        with st.spinner("解析中..."):
                            img_byte_arr = io.BytesIO()
                            image.save(img_byte_arr, format='JPEG') # Convert to JPEG for Vision API
                            content = img_byte_arr.getvalue()
                            
                            vision_image = vision.Image(content=content)
                            response = vision_client.text_detection(image=vision_image)
                            
                            if response.error.message:
                                st.error(f"Error: {response.error.message}")
                            else:
                                passport_data = ocr_utils.parse_response(response)
                                st.session_state['current_mrz_data'] = passport_data
                                st.success("解析完了")
                                
                                with st.expander("解析詳細データ（デバッグ用）"):
                                    st.write("解析結果:", passport_data)
                                    if response.text_annotations:
                                        st.write("生テキスト:", response.text_annotations[0].description)

                if 'current_mrz_data' in st.session_state:
                    data = st.session_state['current_mrz_data']
                    
                    st.markdown("### 解析結果確認")
                    
                    # Top Row
                    r1c1, r1c2, r1c3 = st.columns(3)
                    with r1c1:
                        st.text("旅券番号")
                        st.info(data.get('passport_no', ''))
                    with r1c2:
                        st.text("生年月日")
                        st.info(data.get('birth_date', ''))
                    with r1c3:
                        st.text("性別")
                        st.info(data.get('sex', ''))

                    # Name Row
                    r2c1, r2c2 = st.columns(2)
                    with r2c1:
                        st.text("氏名 (姓)")
                        st.info(data.get('surname', ''))
                    with r2c2:
                        st.text("氏名 (名)")
                        st.info(data.get('given_name', ''))

                    # Domicile / Nationality Row (New)
                    r3c1, r3c2 = st.columns(2)
                    with r3c1:
                        st.text("本籍 (Registered Domicile)")
                        st.info(data.get('domicile', ''))
                    with r3c2:
                        st.text("国籍")
                        st.info(data.get('nationality', ''))

                    # Dates Row (New)
                    r4c1, r4c2 = st.columns(2)
                    with r4c1:
                        st.text("発行年月日")
                        st.info(data.get('issue_date', ''))
                    with r4c2:
                        st.text("有効期間満了日")
                        st.info(data.get('expiry_date', ''))
                    
                    # Input Row
                    r5c1, r5c2 = st.columns(2)
                    with r5c1:
                        st.text("住所 (手入力)")
                        data['address'] = st.text_input("address_input", value=data.get('address', ''), label_visibility="collapsed")
                    with r5c2:
                        st.text("備考")
                        data['note'] = st.text_area("note_input", value=data.get('note', ''), height=38, label_visibility="collapsed")
                    
                    if st.button("登録する", type="primary"):
                        # excel_utils.save_passport_data(excel_path, data, image_filename=uploaded_file.name)
                        
                        # Append to Session State 'manage_df'
                        if 'manage_df' not in st.session_state:
                             # Initialize if managing first time
                             st.session_state['manage_df'] = pd.DataFrame() # Load empty or init structure
                             # Actually we should ideally load existing if any, but we are moving away from file persistence.
                             # If we want to support mixed mode, we'd load here. 
                             # For now, let's assume fresh start or respect existing session.
                             
                        # Create row
                        new_row = {
                            "登録日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "旅券番号": data.get("passport_no", ""),
                            "氏名(姓)": data.get("surname", ""),
                            "氏名(名)": data.get("given_name", ""),
                            "生年月日": data.get("birth_date", ""),
                            "性別": data.get("sex", ""),
                            "国籍": data.get("nationality", ""),
                            "本籍": data.get("domicile", ""),
                            "発行年月日": data.get("issue_date", ""),
                            "有効期間満了日": data.get("expiry_date", ""),
                            "住所(手入力)": data.get("address", ""),
                            "備考": data.get("note", ""),
                            "画像ファイル名": uploaded_file.name
                        }
                        
                        current_df = st.session_state.get('manage_df', pd.DataFrame())
                        new_df = pd.DataFrame([new_row])
                        st.session_state['manage_df'] = pd.concat([current_df, new_df], ignore_index=True)

                        st.success("リストに追加しました！（※ファイル保存はデータ管理タブから行ってください）")
                        st.session_state.pop('current_mrz_data', None)
                             
                        st.rerun()
                            
        # ==========================================
        # TAB 2: Batch Scan
        # ==========================================
        # ==========================================
        # TAB 2: Batch Scan (Upload)
        # ==========================================
        with tab2:
            st.header("複数ファイル一括読み取り")
            st.info("複数のパスポート画像をまとめてアップロードし、一気にリストへ追加します。")
            
            uploaded_files = st.file_uploader("画像をドラッグ＆ドロップ (複数可)", type=['png', 'jpg', 'jpeg', 'heic', 'pdf'], accept_multiple_files=True, key='batch_uploader')
            
            # Batch Settings - Removed FAX mode
            # st.markdown("##### 設定")
            # batch_fax_mode = st.checkbox(...)

            if uploaded_files:
                st.write(f"選択済みファイル: {len(uploaded_files)} 件")
                
                if st.button("一括解析開始", key='btn_batch_ocr'):
                    if not vision_client: st.error("OCR Engine Error")
                    else:
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        count = 0
                        
                        # Use session DF or create if not exists
                        current_df = st.session_state.get('manage_df', pd.DataFrame())
                        
                        # Prepare list for new rows
                        new_rows = []

                        for i, file in enumerate(uploaded_files):
                            status_text.text(f"処理中 ({i+1}/{len(uploaded_files)}): {file.name}")
                            try:
                                # Open Image from memory
                                if file.name.lower().endswith('.heic'):
                                    image = Image.open(file)
                                elif file.name.lower().endswith('.pdf'):
                                    # For batch, we only take the 1st page of PDF for now (Standard passport PDF scan)
                                    # If user needs multi-page OCR from one PDF, logic needs to be loop based.
                                    # Assuming 1 PDF = 1 Page Passport
                                    pages = convert_from_bytes(file.read())
                                    if pages: image = pages[0]
                                    else: 
                                        st.error(f"{file.name}: PDF page empty")
                                        continue
                                else:
                                    image = Image.open(file)

                                # Vision API
                                img_byte_arr = io.BytesIO()
                                image.save(img_byte_arr, format='JPEG')
                                content = img_byte_arr.getvalue()
                                vision_image = vision.Image(content=content)
                                response = vision_client.text_detection(image=vision_image)
                                
                                # Parse
                                p_data = ocr_utils.parse_response(response)
                                
                                # Create Row Data
                                row = {
                                    "登録日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "旅券番号": p_data.get("passport_no", ""),
                                    "氏名(姓)": p_data.get("surname", ""),
                                    "氏名(名)": p_data.get("given_name", ""),
                                    "生年月日": p_data.get("birth_date", ""),
                                    "性別": p_data.get("sex", ""),
                                    "国籍": p_data.get("nationality", ""),
                                    "本籍": p_data.get("domicile", ""),
                                    "発行年月日": p_data.get("issue_date", ""),
                                    "有効期間満了日": p_data.get("expiry_date", ""),
                                    "住所(手入力)": p_data.get("address", ""),
                                    "備考": p_data.get("note", ""),
                                    "画像ファイル名": file.name
                                }
                                new_rows.append(row)
                                count += 1
                                
                            except Exception as e:
                                st.error(f"Error {file.name}: {e}")
                            
                            progress_bar.progress((i + 1) / len(uploaded_files))
                        
                        if new_rows:
                            new_df = pd.DataFrame(new_rows)
                            # Append to manage_df in session (Memory Only)
                            # If manage_df is loaded from excel initially, we append to it.
                            # But since we want to STOP using excel file as storage, we effectively treat manage_df as the master.
                            if 'manage_df' not in st.session_state:
                                st.session_state['manage_df'] = excel_utils.load_data_as_df(excel_path)
                            
                            st.session_state['manage_df'] = pd.concat([st.session_state['manage_df'], new_df], ignore_index=True)

                        status_text.text("完了")
                        st.success(f"{count} 件をリストに追加しました。「データ管理」タブで確認・保存してください。")

        # ==========================================
        # TAB 3: Data Management
        # ==========================================
        # ==========================================
        # TAB 3: Data Management
        # ==========================================
        with tab3:
            st.warning("⚠️ データは一時保存されています。クラウド上には保存されません。必ず最後にダウンロードしてください。")

            # Initialize session data
            if 'manage_df' not in st.session_state:
                st.session_state['manage_df'] = pd.DataFrame(columns=[
                "登録日時", "旅券番号", "氏名(姓)", "氏名(名)", 
                "生年月日", "性別", "国籍", "本籍", "発行年月日", "有効期間満了日", 
                "住所(手入力)", "備考", "画像ファイル名"
            ])
            
            # --- 1. Passport Validity Check Section ---
            st.markdown("### 🛂 渡航要件チェック (残存有効期間)")
            with st.expander("チェック機能を開く", expanded=True):
                ck1, ck2, ck3 = st.columns([2, 2, 2])
                with ck1:
                    entry_date = st.date_input("入国予定日", help="渡航先の国に入国する日付")
                with ck2:
                    required_days = st.number_input("必要な残存日数", min_value=0, value=180, step=30, help="例: 6ヶ月なら約180日")
                with ck3:
                    st.write("") # Spacer
                    check_clicked = st.button("✅ チェック実行", type="primary")
            
            # --- Perform Check Logic ---
            df_current = st.session_state['manage_df']
            
            if check_clicked and not df_current.empty:
                # Create a copy for analysis
                check_df = df_current.copy()
                
                def validate_expiry(expiry_str):
                    if not expiry_str or pd.isna(expiry_str):
                        return "不明 (空欄)"
                    try:
                        exp_dt = datetime.strptime(str(expiry_str).strip(), "%Y/%m/%d").date()
                        limit_date = entry_date + timedelta(days=required_days)
                        if exp_dt >= limit_date: return "OK"
                        else: return "NG (期限切れ/残存不足)"
                    except: return "不明 (形式エラー)"

                check_df["判定結果"] = check_df["有効期間満了日"].apply(validate_expiry)
                
                ng_items = check_df[check_df["判定結果"].str.contains("NG", na=False)]
                
                if not ng_items.empty:
                    st.error(f"⚠️ {len(ng_items)} 件が要件を満たしていません！")
                    st.dataframe(ng_items[["旅券番号", "氏名(姓)", "有効期間満了日", "判定結果"]])
                else:
                    st.success("🎉 全員OKです！")

            # --- 2. Data Cleaning Section (New) ---
            st.markdown("### 🧹 データ補正")
            with st.expander("データのクレンジング（本籍の修正、全角→半角変換など）", expanded=False):
                st.info("「本籍」のノイズ除去に加え、全角英数字（例：ＫＡＮＡＴＡ）を半角（KANATA）に統一します。")
                if st.button("✨ データを一括補正・正規化する"):
                    if not st.session_state['manage_df'].empty:
                        df_clean = st.session_state['manage_df'].copy()
                        
                        count_fixed = 0
                        
                        # Apply Cleaning using the same logic as ocr_utils
                        # Use direct module access ensuring we get the latest
                        import ocr_utils
                        
                        # Use the new utility from ocr_utils if available, or define local
                        if hasattr(ocr_utils, 'normalize_text'):
                            norm_func = ocr_utils.normalize_text
                        else:
                            import unicodedata
                            def norm_func(t): return unicodedata.normalize('NFKC', str(t)).strip() if t else t

                        def clean_domicile(val):
                            if not val or pd.isna(val): return val
                            # First normalize full-width
                            val = norm_func(val)
                            
                            val_str = str(val).upper()
                            
                            # 1. Check against Prefecture List
                            if hasattr(ocr_utils, 'JAPAN_PREFECTURES'):
                                for pref in ocr_utils.JAPAN_PREFECTURES:
                                    if pref in val_str:
                                        return pref
                            return val # Return original if no prefecture found
                        
                        # Check diff
                        for index, row in df_clean.iterrows():
                            # Fix Domicile
                            orig_dom = row['本籍']
                            cleaned_dom = clean_domicile(orig_dom)
                            
                            # Fix other text fields (Name, Passport No, etc) - Normalization only
                            # List of columns to normalize
                            target_cols = ["旅券番号", "氏名(姓)", "氏名(名)", "生年月日", "性別", "国籍", "発行年月日", "有効期間満了日"]
                            
                            row_changed = False
                            
                            if orig_dom != cleaned_dom:
                                df_clean.at[index, '本籍'] = cleaned_dom
                                row_changed = True
                                
                            for col in target_cols:
                                if col in row:
                                    orig_val = row[col]
                                    if orig_val and not pd.isna(orig_val):
                                        new_val = norm_func(orig_val)
                                        if orig_val != new_val:
                                            df_clean.at[index, col] = new_val
                                            row_changed = True
                            
                            if row_changed:
                                count_fixed += 1
                        
                        st.session_state['manage_df'] = df_clean
                        
                        # IMPORTANT: Clear data_editor state to force refresh
                        if "data_editor_mem" in st.session_state:
                            del st.session_state["data_editor_mem"]
                            
                        if count_fixed > 0:
                            st.success(f"{count_fixed} 件のデータを補正しました！")
                            st.rerun()
                        else:
                            st.info("補正が必要なデータは見つかりませんでした（すべて正常か、マッチしませんでした）。")
                    else:
                        st.warning("データが空です。")

            st.markdown("---")

            # --- 3. Data Editor Section ---
            df_current = st.session_state['manage_df']
            
            if not df_current.empty:
                if "削除対象" not in df_current.columns:
                    df_current.insert(0, "削除対象", False)

                # Bulk Select
                b1, b2, b3 = st.columns([1, 1, 4])
                with b1: 
                    if st.button("☑️ 全選択"):
                        df_current["削除対象"] = True
                        st.session_state['manage_df'] = df_current
                        st.rerun()
                with b2:
                    if st.button("☐ 全解除"):
                        df_current["削除対象"] = False
                        st.session_state['manage_df'] = df_current
                        st.rerun()

                edited_df = st.data_editor(
                    df_current,
                    key="data_editor_mem",
                    num_rows="fixed",
                    use_container_width=True,
                    column_config={"削除対象": st.column_config.CheckboxColumn("削除", default=False)},
                    disabled=["登録日時", "画像ファイル名"]
                )
                
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("🗑️ 選択行を削除"):
                         # Remove from memory
                        new_df = edited_df[edited_df["削除対象"] == False].drop(columns=["削除対象"], errors='ignore')
                        st.session_state['manage_df'] = new_df
                        st.success("削除しました")
                        st.rerun()
                with c2:
                    if st.button("💾 編集を確定"):
                        # Just update memory state from editor
                        final = edited_df.drop(columns=["削除対象"], errors='ignore')
                        st.session_state['manage_df'] = final
                        st.success("編集内容を確定しました")
                        st.rerun()
                
                st.markdown("### データ出力")
                # Excel Download
                buffer = io.BytesIO()
                dl_df = st.session_state['manage_df'].copy()
                if "削除対象" in dl_df.columns:
                    dl_df = dl_df.drop(columns=["削除対象"])
                
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    dl_df.to_excel(writer, index=False, sheet_name='Passport Data')
                
                st.download_button(
                    label="📥 Excelファイルとしてダウンロード",
                    data=buffer.getvalue(),
                    file_name=f"passport_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )

            else:
                st.info("データはありません。")


import re
from datetime import datetime
from collections import defaultdict

month_map = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"
}

# Image Preprocessing
import cv2
import numpy as np
from PIL import Image

def preprocess_image_for_ocr(pil_image):
    """
    低画質・FAX画像向けの前処理を行う。
    1. グレースケール化
    2. 平滑化 (ノイズ除去)
    3. 膨張処理 (かすれた文字を繋げる)
    Returns: Processed PIL Image (JPEG bytes are handled by caller typically, but here we return PIL)
    """
    # Convert PIL to OpenCV (BGR)
    img = np.array(pil_image)
    if img.shape[2] == 4: # RGBA -> RGB
         img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
    
    # 1. Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    
    # 2. Gaussian Blur (Reduce dot noise)
    # カーネルサイズ (3,3) 程度で軽くぼかす
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    
    
    # 3. Dilation (Thicken text)
    # 文字が途切れている場合に有効。カーネルサイズは小さめに。
    kernel = np.ones((2, 2), np.uint8)
    dilated = cv2.dilate(blurred, kernel, iterations=1)
    
    # Optional: Contrast Enhancement (CLAHE)
    # コントラストを強調して文字をよりくっきりさせる
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    enhanced = clahe.apply(dilated)

    # Convert back to PIL
    final_img = Image.fromarray(enhanced)
    return final_img


# 日本の都道府県リスト（ローマ字・ヘボン式）
JAPAN_PREFECTURES = {
    "HOKKAIDO", "AOMORI", "IWATE", "MIYAGI", "AKITA", "YAMAGATA", "FUKUSHIMA",
    "IBARAKI", "TOCHIGI", "GUNMA", "SAITAMA", "CHIBA", "TOKYO", "KANAGAWA",
    "NIIGATA", "TOYAMA", "ISHIKAWA", "FUKUI", "YAMANASHI", "NAGANO", "GIFU",
    "SHIZUOKA", "AICHI", "MIE", "SHIGA", "KYOTO", "OSAKA", "HYOGO", "NARA", "WAKAYAMA",
    "TOTTORI", "SHIMANE", "OKAYAMA", "HIROSHIMA", "YAMAGUCHI",
    "TOKUSHIMA", "KAGAWA", "EHIME", "KOCHI",
    "FUKUOKA", "SAGA", "NAGASAKI", "KUMAMOTO", "OITA", "MIYAZAKI", "KAGOSHIMA", "OKINAWA"
}

def parse_response(response):
    """
    Google Vision APIのレスポンスオブジェクトを受け取り、
    1. MRZ解析 (テキスト全体から)
    2. VIZ解析 (座標ベース)
    を行ってマージする。
    """
    full_text = response.text_annotations[0].description if response.text_annotations else ""
    annotations = response.text_annotations[1:] if len(response.text_annotations) > 1 else []

    # 1. MRZ Parsing
    mrz_data = parse_mrz_text(full_text)
    
    # 2. VIZ Parsing (Layout based)
    viz_data = parse_viz_layout(annotations, full_text=full_text)
    
    # 3. Merge (VIZ usually has higher accuracy for visual fields, MRZ for raw structure)
    data = {
        "passport_no": merge_val(mrz_data.get('passport_no'), viz_data.get('passport_no')),
        "surname": merge_val(mrz_data.get('surname'), viz_data.get('surname')),
        "given_name": merge_val(mrz_data.get('given_name'), viz_data.get('given_name')),
        "birth_date": merge_val(mrz_data.get('birth_date'), viz_data.get('birth_date')),
        "expiry_date": merge_val(mrz_data.get('expiry_date'), viz_data.get('expiry_date')),
        "sex": merge_val(mrz_data.get('sex'), viz_data.get('sex')),
        "nationality": merge_val(mrz_data.get('nationality'), viz_data.get('nationality'), default="JPN"),
        "domicile": merge_val(mrz_data.get('domicile'), viz_data.get('domicile')), # Added Domicile
        "issue_date": merge_val(mrz_data.get('issue_date'), viz_data.get('issue_date')), # Added Issue Date
        "raw_mrz": mrz_data.get('raw_mrz', "")
    }
    
    return data

def merge_val(v1, v2, default=""):
    if not v1 and not v2: return default
    if v1 and not v2: return v1
    if not v1 and v2: return v2
    return v2

# ----------------------------------------------------------------------------
# Layout Based Parsing (VIZ)
# ----------------------------------------------------------------------------

def parse_viz_layout(annotations, full_text=""):
    data = {}
    
    # ... (get_center and get_bbox remain same) ...

    # Helper to calculate center of word
    def get_center(ann):
        vs = ann.bounding_poly.vertices
        x = sum([v.x for v in vs]) / 4
        y = sum([v.y for v in vs]) / 4
        return x, y

    # Helper to get bounding box
    def get_bbox(ann):
        vs = ann.bounding_poly.vertices
        min_x = min([v.x for v in vs])
        max_x = max([v.x for v in vs])
        min_y = min([v.y for v in vs])
        max_y = max([v.y for v in vs])
        return min_x, min_y, max_x, max_y

    # Update Targets: Use simpler single-word labels for better matching results.
    targets = [
        {'key': 'passport_no', 'labels': ['Passport', 'No', '旅券番号'], 'dir': 'BELOW', 'pat': r'([A-Z]{2}\s*\d{7})'},
        {'key': 'surname', 'labels': ['Surname', '姓'], 'dir': 'BELOW', 'pat': r'([A-Z]+)'},
        {'key': 'given_name', 'labels': ['Given', '名'], 'dir': 'BELOW', 'pat': r'([A-Z]+)'},
        {'key': 'nationality', 'labels': ['Nationality', '国籍'], 'dir': 'BELOW', 'pat': r'(JAPAN|JPN)'},
        {'key': 'birth_date', 'labels': ['Birth', '生年月日'], 'dir': 'BELOW', 'pat': r'\d{1,2}\s+[A-Z]{3}\s+\d{4}'},
        {'key': 'sex', 'labels': ['Sex', '性別'], 'dir': 'BELOW', 'pat': r'[MF]'},
        {'key': 'issue_date', 'labels': ['Issue', '発行年月日'], 'dir': 'BELOW', 'pat': r'\d{1,2}\s+[A-Z]{3}\s+\d{4}'}, # Added Issue
        {'key': 'domicile', 'labels': ['Registered', 'Domicile', '本籍'], 'dir': 'BELOW', 'pat': r'([A-Z]+)'}, # Added Domicile
        {'key': 'expiry_date', 'labels': ['Expiry', '有効期間満了日'], 'dir': 'BELOW', 'pat': r'\d{1,2}\s+[A-Z]{3}\s+\d{4}'}
    ]

    # Stop words
    stop_words = {
        "NAME", "SURNAME", "GIVEN", "DATE", "BIRTH", "EXPIRY", "SEX", "NATIONALITY", "PASSPORT", "NO", "JAPAN", "ISSUING", "COUNTRY", 
        "MINISTRY", "FOREIGN", "AFFAIRS", "REGISTERED", "DOMICILE", "SIGNATURE", "BEARER", "AUTHORITY", "TYPE", "JPN", "ISSUE",
        "旅券番号", "姓", "名", "国籍", "生年月日", "性別", "有効期間満了日", "所持人自署", "発行官庁", "型", "発行国", "本籍", "発行年月日"
    }

    # Pre-process: Identify Label Annotations
    matched_labels = defaultdict(list)
    
    for ann in annotations:
        text = ann.description.strip().upper().replace('.', '').replace(':', '')
        for tgt in targets:
            for lbl in tgt['labels']:
                lbl_upper = lbl.upper().replace('.', '').replace(':', '')
                # Strict check for short words, containment for long words
                if lbl_upper == text:
                    matched_labels[tgt['key']].append(ann)
                elif len(lbl_upper) > 3 and lbl_upper in text:
                    # Allow "EXPIRY" in "DATE OF EXPIRY"
                    matched_labels[tgt['key']].append(ann)

    # Search Values relative to Labels
    for tgt in targets:
        key = tgt['key']
        labels_found = matched_labels[key]
        if not labels_found:
            continue
            
        labels_found.sort(key=lambda a: (get_bbox(a)[1], get_bbox(a)[0]))
        base_ann = labels_found[0]
        
        bx1, by1, bx2, by2 = get_bbox(base_ann)
        base_h = by2 - by1
        base_w = bx2 - bx1
        
        roi_candidates = []
        
        for ann in annotations:
            if ann == base_ann: continue
            
            # Skip if this annotation matches ANY label keyword (It's likely another label)
            txt_upper = ann.description.upper().replace('.', '').replace(':', '').strip()
            
            # Japanese stop word check (partial match allowed for short japanese words?)
            # No, text_annotations usually split by word.
            if key != 'nationality' and txt_upper in stop_words:
                 continue
            
            # Strict stop for JAPAN if key is nationality (it's the value itself)
            # But for other keys, "JAPAN" is a stop word (next field label "JAPAN / Nationality")

            ax1, ay1, ax2, ay2 = get_bbox(ann)
            acx, acy = get_center(ann)
            
            is_candidate = False
            
            if tgt['dir'] == 'BELOW':
                # Strictly below
                if ay1 > (by1 + base_h * 0.1): # Start just below top of label (sometimes label is multiline or big)
                     # Check if it is *immediately* below.
                     # Max gap: 2 lines height max.
                     if (ay1 - by2) < (base_h * 2.5): # Slightly relaxed vertical
                         # Check X alignment: mostly overlaps with the label column
                         # Japanese passport: Left aligned or Center aligned.
                         # IMPORTANT: If label is "Expiry" (at end of line), the value "15 SEP 2028" DETECTED TO THE LEFT.
                         # So we need a large Left tolerance.
                         # But not too large to cross into "Date of issue" column (which is to the left).
                         if (bx1 - base_w*8) < acx < (bx2 + base_w*5):
                             is_candidate = True
            
            if is_candidate:
                roi_candidates.append(ann)
        
        if roi_candidates:
            roi_candidates.sort(key=lambda a: (get_bbox(a)[1], get_bbox(a)[0]))
            
            combined_text = ""
            for ann in roi_candidates:
                word = ann.description.strip()
                w_upper = word.upper().replace('.','')
                
                # Check stop words
                if key != 'nationality' and w_upper in stop_words:
                     break # Stop reading further
                
                # Check Japanese specific stop words containment (OCR might merge "名/Given")
                if any(sw in word for sw in ["名", "姓", "国籍", "生年月日", "性別", "有効期間"]):
                    if len(word) > 1 and key not in ['surname', 'given_name']: # Name fields might contain Kanji in JP passport? No, usually English VIZ.
                        break
                
                combined_text += " " + word
            
            combined_text = combined_text.strip()
            
            # Clean up
            if key in ['birth_date', 'expiry_date', 'issue_date']:
                 date_val = parse_date_from_text(combined_text)
                 if date_val: data[key] = date_val
            
            elif key == 'sex':
                m = re.search(r'\b([MF])\b', combined_text.upper())
                if m: data[key] = m.group(1)
            
            elif key == 'nationality':
                # Strict check for JPN/JAPAN
                if 'JAPAN' in combined_text.upper() or 'JPN' in combined_text.upper():
                    data[key] = "JPN"
            
            elif key == 'domicile':
                # -----------------------------------------------------------
                # 都道府県ホワイトリストによる照合（Validation & Sanitization）
                # -----------------------------------------------------------
                found_pref = None
                upper_text = combined_text.upper()
                
                # 1. 完全一致検索（ノイズの中に都道府県名が含まれているか）
                # 例: "Sex OKINAWA of 所持" -> "OKINAWA"
                for pref in JAPAN_PREFECTURES:
                    if pref in upper_text:
                        found_pref = pref
                        break
                
                if found_pref:
                    data[key] = found_pref
                else:
                    # 見つからない場合は従来のクリーニングロジックで頑張る
                    # （OCRミスで "T0KYO" となっている場合などへの最低限の対応）
                    clean_val = re.sub(r'[\*0-9<:;,\.]', '', combined_text).strip()
                    
                    # 日本語ラベルの除去
                    m_jp = re.search(r'[発行年月日]', clean_val)
                    if m_jp:
                        clean_val = clean_val[:m_jp.start()].strip()

                    valid_parts = [w for w in clean_val.split() if len(w) > 1]
                    if valid_parts:
                        data[key] = " ".join(valid_parts)

            elif key == 'passport_no':
                m = re.search(r'([A-Z]{2}\s*\d{7})', combined_text)
                if m: data[key] = m.group(1).replace(' ', '')

            else:
                # Name cleaning
                clean_val = re.sub(r'[0-9<:;,\.]', '', combined_text).strip()
                # Remove common garbage like "/" or "Nati" if partly matched
                clean_val = re.sub(r'/[a-zA-Z]*', '', clean_val).strip()
                if clean_val: data[key] = clean_val

    # Special Fallback for Passport No (search in FULL TEXT)
    if not data.get('passport_no') and full_text:
        # Search for MJ 1234567 or similar in the whole text
        m = re.search(r'([A-Z]{2})\s*(\d{7})', full_text)
        if m:
            data['passport_no'] = f"{m.group(1)}{m.group(2)}"

    return data


def parse_date_from_text(text):
    # Pattern: 13 FEB 2020 or 13FEB2020 or 13 FEB2020
    # Normalize: Remove non-alphanumeric except space
    clean = re.sub(r'[^A-Z0-9\s]', ' ', text.upper())
    norm = re.sub(r'\s+', ' ', clean).strip()
    
    # Try with English Month
    for mon, num in month_map.items():
        if mon in norm:
            # Match variants: "13 FEB 2020", "13FEB 2020", "FEB 13 2020"
            # 1. DD MMM YYYY or DDMMM YYYY
            # Look for YYYY (19xx or 20xx)
            year_match = re.search(r'\b(19|20)\d{2}\b', norm)
            if not year_match: continue
            
            y_str = year_match.group(0)
            
            # Look for Day (1-31) exclude year
            # Remove year from string to avoid confusion
            rem_str = norm.replace(y_str, '')
            
            # Simple digit search nearby the month
            day_match = re.search(r'\b(\d{1,2})\b', rem_str)
            if day_match:
                d_str = day_match.group(1)
                return f"{y_str}/{num}/{d_str.zfill(2)}"
                
    return ""


# ----------------------------------------------------------------------------
# MRZ Parsing (Robust Fallback)
# ----------------------------------------------------------------------------

def parse_mrz_text(text):
    data = {}
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Identify MRZ lines
    candidates = []
    for line in lines:
        clean = line.replace(' ', '').upper()
        # MRZ line is 44 chars, but OCR might split or shrink
        if len(clean) > 20: 
            candidates.append(clean)
            
    line1 = line2 = None
    for i, seq in enumerate(candidates):
        # Line 1: P<JPN...
        if seq.startswith('P') and '<' in seq:
            # Score it? count <
            if seq.count('<') >= 2:
                # Look for Line 2
                if i + 1 < len(candidates):
                    seq2 = candidates[i+1]
                    # Line 2 often starts with passport no (alphanum) and has digits
                    # Check for digit density
                    digit_count = sum(c.isdigit() for c in seq2)
                    if digit_count > 5:
                        line1, line2 = seq, seq2
                        
                        # MRZ Specific Correction (O vs 0)
                        # Line 2: Passport No (char 0-9), DOB (13-19), Expiry (21-27) are usually Digits.
                        # Force O -> 0 for date fields
                        l2_chars = list(line2)
                        
                        # Fix Passport No (First 9 chars: often ambiguous, but usually Alphanumeric)
                        # Fix Dates (DOB: 13-18, Expiry: 21-26, Personal No: 28-32??)
                        # Indices are 0-based.
                        # Date positions: 13,14, 15,16, 17,18 (DOB)
                        #                 21,22, 23,24, 25,26 (Expiry)
                        for idx in [13,14,15,16,17,18, 21,22,23,24,25,26]:
                            if idx < len(l2_chars):
                                if l2_chars[idx] == 'O': l2_chars[idx] = '0'
                                if l2_chars[idx] == 'I': l2_chars[idx] = '1'
                                if l2_chars[idx] == 'D': l2_chars[idx] = '0'
                                if l2_chars[idx] == 'S': l2_chars[idx] = '5'
                                if l2_chars[idx] == 'B': l2_chars[idx] = '8'
                        
                        line2 = "".join(l2_chars)
                        break
    
    if line1 and line2:
        data['raw_mrz'] = f"{line1}\n{line2}"
        try:
            name_area = line1[5:]
            if '<<' in name_area:
                parts = name_area.split('<<')
                data['surname'] = parts[0].replace('<', '').strip()
                if len(parts) > 1: data['given_name'] = parts[1].replace('<', ' ').strip()
            else:
                 # Fallback split
                 parts = [p for p in name_area.split('<') if p]
                 if parts:
                     data['surname'] = parts[0]
                     data['given_name'] = " ".join(parts[1:])
        except: pass
        
        try:
            # Passport No extraction from Line 2
            # First 9 chars usually. 
            # Sometimes OCR merges or adds noise.
            # Regex for [A-Z0-9]{9}
            m = re.match(r'([A-Z0-9]{9})', line2)
            if m: data['passport_no'] = m.group(1).replace('<', '')
            
            # Find DOB: look for digits
            # usually pos 13-19
            if len(line2) > 19:
                dob = line2[13:19]
                if dob.isdigit(): data['birth_date'] = convert_yymmdd_to_fmt(dob)
                data['sex'] = line2[20]
                exp = line2[21:27]
                if exp.isdigit(): data['expiry_date'] = convert_yymmdd_to_fmt(exp, future=True)
        except: pass
        
    return data

def convert_yymmdd_to_fmt(yymmdd, future=False):
    if not yymmdd or len(yymmdd) < 6: return yymmdd
    try:
        y = int(yymmdd[0:2])
        m = int(yymmdd[2:4])
        d = int(yymmdd[4:6])
        if m < 1 or m > 12: return yymmdd # Invalid month
        current_yy = int(datetime.now().year) % 100
        
        if future:
             full_year = 2000 + y
        else:
             full_year = 1900 + y if y > current_yy else 2000 + y
             
        return f"{full_year}/{str(m).zfill(2)}/{str(d).zfill(2)}"
    except:
        return yymmdd

# For backward compatibility
def parse_passport_text(text):
    return parse_mrz_text(text)

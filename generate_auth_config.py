import yaml
import bcrypt

# streamlit-authenticator用のハッシュ生成 (bcrypt使用)
passwords = ['abc123', 'def456']
hashed_passwords = [bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode() for p in passwords]

config = {
    'credentials': {
        'usernames': {
            'user1': {
                'name': 'User One',
                'password': hashed_passwords[0],
                'email': 'user1@gmail.com',
                'logged_in': False,
                'data_dir': './data/user1'
            },
            'user2': {
                'name': 'User Two',
                'password': hashed_passwords[1],
                'email': 'user2@gmail.com',
                'logged_in': False,
                'data_dir': './data/user2'
            }
        }
    },
    'cookie': {
        'expiry_days': 30,
        'key': 'some_signature_key',
        'name': 'some_cookie_name'
    },
    'preauthorized': {
        'emails': ['user1@gmail.com']
    }
}

with open('auth_config.yaml', 'w') as file:
    yaml.dump(config, file, default_flow_style=False)

print("auth_config.yaml generated.")
print(f"User1 Password: abc123")
print(f"User2 Password: def456")

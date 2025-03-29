import secrets
import string


chars = string.ascii_letters + string.digits + '!@#$%^&*(-_=+)'
secret_key = ''.join(secrets.choice(chars) for _ in range(50))
print('Generated Django SECRET_KEY:')
print(secret_key)
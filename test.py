from datetime import date,datetime
import os
import certifi
import ssl
today = date.today()
today_str = today.strftime("%m-%d")
print(type(today_str))
print(today_str)

ssl_context = os.environ.get("SSL_CERT_FILE")
if(ssl_context):
    print(ssl_context)
else:
    cert = ssl.create_default_context(cafile=certifi.where())
    print(cert)
import requests
import ssl
from requests.adapters import HTTPAdapter

class LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1      # 오래된 TLS 1.0 허용
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        context.set_ciphers('DEFAULT:@SECLEVEL=0')
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.load_cert_chain(certfile='cert.pem')
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

s = requests.Session()
s.mount('https://', LegacySSLAdapter())

headers = {'content-type': 'text/xml'}
resp = s.post(
    "https://192.168.219.8:8888/devicetoken/request",
    data={"DeviceToken": "xxxxxxxxxxx"},
    headers=headers,
    stream=True,
    verify=False
)
print(resp.status_code)
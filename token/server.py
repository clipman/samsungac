from http.server import HTTPServer, BaseHTTPRequestHandler
import ssl

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        request_path = self.path

        print("\n----- Request Start ----->\n")
        print("Request path:", request_path)
        print("Request headers:", self.headers)
        print("<----- Request End -----\n")

        self.send_response(200)
        self.send_header("Set-Cookie", "foo=bar")
        self.end_headers()

    def do_POST(self):
        request_path = self.path

        print("\n----- Request Start ----->\n")
        print("Request path:", request_path)

        request_headers = self.headers
        content_length = request_headers.get('Content-Length')
        length = int(content_length) if content_length else 0

        print("Content Length:", length)
        print("Request headers:", request_headers)
        print("Request payload:", self.rfile.read(28))
        print("Body:", self)
        print("<----- Request End -----\n")

        self.send_response(200)
        self.end_headers()

    do_PUT = do_POST
    do_DELETE = do_GET

def main():
    port = 8889
    print('Listening on localhost:%s' % port)
    server = HTTPServer(('', port), RequestHandler)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.set_ciphers('DEFAULT:@SECLEVEL=0')   # 약한 해시(MD5 등) 인증서 허용
    context.load_cert_chain(certfile='cert.pem')
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    server.socket = context.wrap_socket(server.socket, server_side=True)

    server.serve_forever()

if __name__ == "__main__":
    main()
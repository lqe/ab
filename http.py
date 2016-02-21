import re
import socket
import warnings
from datetime import datetime

from utils import gzip_decode, chunked_decode

CRLF = '\r\n'


class Response(object):
    def __init__(self, text=''):
        self.text = text
        self.header = dict()
        self.origin_header = ''
        self.body = ''
        self.http_version = 'unkown'
        self.status_code = -1
        self.reason_phrase = 'no status_code in response'
        self._parse(text)

    @property
    def status_line(self):
        return '%s %d %s' % (self.http_version, self.status_code, self.reason_phrase)

    @property
    def len_of_body(self):
        return self.header.get('Content-Length', len(self.body))

    @property
    def len_of_text(self):
        return len(self.text)

    @property
    def decoded_body(self):
        body = self.body
        if self.header.get('Transfer-Encoding', None) == 'chunked':
            body = chunked_decode(body)
        if self.header.has_key('Content-Encoding'):
            encoding = self.header.get('Content-Encoding')
            if encoding == 'gzip':
                body = gzip_decode(body)
        return body

    def _parse(self, text):
        pos1 = text.find(CRLF)
        pos2 = text.find(CRLF * 2)
        if pos2 != -1:
            self._parse_status_line(text[:pos1])
            self._parse_header(text[pos1 + 2:pos2])
            self.body = text[pos2 + 4:]
            if not self.header.has_key('Content-Length'):
                self.header['Content-Length'] = len(self.body)

    def _parse_status_line(self, status_line):
        '''acquire http_version, status_code, reason_phrase from status_line '''
        try:
            self.http_version, self.status_code, self.reason_phrase = tuple(status_line.split(' ', 2))
            self.http_version = self.http_version.strip()
            self.status_code = int(self.status_code)
            self.reason_phrase = self.reason_phrase.strip()
        except ValueError, e:
            error_code = 'http_version, status_code, reason_phrase = {}' \
                .format(tuple(status_line.split(' ', 2)))
            warnings.warn(e.message + '. error_code : {}'.format(error_code))

    def _parse_header(self, header):
        self.origin_header = header
        for line in header.split(CRLF):
            if ':' in line.strip():
                k, v = tuple(line.split(':', 1))
                self.header[k.strip()] = v.strip()

    def __str__(self):
        return self.text


class Request(object):
    def __init__(self, header=None, data=None, method='GET', request_url='/', http_version='HTTP/1.1', protocal='http'):
        super(Request, self).__init__()
        self.method = method.upper()
        self.request_url = request_url
        self.http_version = http_version
        self.protocal = protocal
        self.header = header
        self.data = data

    @property
    def request_status_line(self):
        return '%s %s %s' % (self.method, self.request_url, self.http_version)

    @property
    def request_header(self):
        temp = []
        for k, v in self.header.iteritems():
            temp.append('%s: %s' % (k, v))
        return CRLF.join(temp)

    @property
    def request_text(self):
        text = []
        text.append(self.request_status_line)
        text.append(self.request_header)
        text.append(CRLF)
        if self.data:
            text.append(self.data)
        return CRLF.join(text)

    def __str__(self):
        return self.request_text

    __repr__ = __str__


class AprTime(object):
    def __init__(self):
        self._start = None  # Start of connection
        self._connect = None  # Connected start writing
        self._endwrite = None  # Request written
        self._beginread = None  # First byte of input
        self._done = None

    @property
    def connect(self):
        return (self._connect - self._start).total_seconds()

    @property
    def processing(self):
        return (self._done - self._connect).total_seconds()

    @property
    def waiting(self):
        return (self._beginread - self._endwrite).total_seconds()

    @property
    def total(self):
        return (self._done - self._start).total_seconds()


class SocketHandle(object):
    def __init__(self, family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0, _sock=None):
        self.apr_time = None
        self._sock = socket.socket(family, type, proto, _sock)

    def apr_time_init(self):
        self.apr_time = AprTime()

    def connect(self, host='127.0.0.1', port=80):
        self.apr_time._start = datetime.now()
        self._sock.connect((host, port))
        self.apr_time._connect = datetime.now()

    def send(self, request_text):
        if self.apr_time._connect is None:
            self.apr_time._start = self.apr_time._connect = datetime.now()
        self.apr_time._beginwrite = datetime.now()
        self._sock.send(request_text)
        self.apr_time._endwrite = datetime.now()

    def recv(self, buffersize=1024*10):
        text = ''
        body_length = 0
        res = self._sock.recv(1)
        self.apr_time._beginread = datetime.now()
        while res:
            text += res
            flag = res.find(CRLF * 2)
            if flag != -1:
                body_length += (len(res) - flag - 4)
                break
            res = self._sock.recv(buffersize)

        C_L = T_E = None
        temp = re.search(r'Content-Length *: *(\d+)', text)
        try:
            C_L = int(temp.groups()[0])
        except:
            pass

        if C_L is not None:
            res = self._sock.recv(buffersize)
            while res:
                text += res
                body_length += len(res)
                if C_L != body_length:
                    res = self._sock.recv(buffersize)
                else:
                    break
        else:
            temp = re.search(r'Transfer-Encoding *: *([a-zA-Z]+)', text)
            try:
                T_E = temp.groups()[0]
            except:
                pass

            if T_E == 'chunked' and text.endswith('\r\n0\r\n\r\n'):
                pass  # has recv all bytes.
            else:
                res = self._sock.recv(buffersize)
                while res:
                    text += res
                    if T_E == 'chunked' and text.endswith('\r\n0\r\n\r\n'):
                        break
                    else:
                        res = self._sock.recv(buffersize)

        self.apr_time._done = datetime.now()
        return text

    def modify_windowsize(self, buf_size=None):
        if buf_size is not None:
            self._sock.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, buf_size)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buf_size)

            bufsize = self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
            print "Modify Buffer size [After]: %d" % bufsize

    def quit(self):
        self._sock.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.quit()

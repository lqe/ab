import sys
import re
import os
import base64
import warnings
import socket
from Queue import Queue, Empty
from threading import Thread, Lock
from datetime import datetime

from http import SocketHandle, Request, Response
from utils import Calc


class Ab(object):
    '''ab [ -A auth-username:password ] [ -b windowsize ] [ -c concurrency ] [ -C cookie-name=value ]
          [ -d ] [ -e csv-file ] [ -f protocol ] [ -g gnuplot-file ] [ -h ] [ -H custom-header ] [ -i ]
          [ -k ] [ -n requests ] [ -p POST-file ] [ -P proxy-auth-username:password ] [ -q ] [ -r ]
          [ -s ] [ -S ] [ -t timelimit ] [ -T content-type ] [ -u PUT-file ] [ -v verbosity] [ -V ] [ -w ]
          [ -x <table>-attributes ] [ -X proxy[:port] ] [ -y <tr>-attributes ] [ -z <td>-attributes ]
          [ -Z ciphersuite ] [http[s]://]hostname[:port]/path'''
    VERSION = '1.0'

    def __init__(self, args):
        self.hostname = '127.0.0.1'
        self.port = 80

        self.protocal = 'http'
        self.method = 'GET'
        self.path = '/'
        self.http_version = 'HTTP/1.1'
        self.header = {
            'Host': '%s:%d' % (self.hostname, self.port),
            'User-Agent': 'ApacheBench/%s' % Ab.VERSION,
            'Accept': '*/*'
        }
        self.data = None
        self.request = None
        self.response = None

        self.concurrency_users = 1  # Number of multiple requests to make at a time
        self.number_of_requests = 1  # Number of requests to perform
        self.verbosity = 1  # How much troubleshooting info to print
        self.timeout = 30  # Seconds to max. wait for each response
        self.max_seconds = 50000  # econds to max. to spend on benchmarking
        self.keep_alive = False  # Use HTTP KeepAlive feature
        self.windowsize = None  # Size of TCP send/receive buffer, in bytes
        self._opts = Opts(self.args_parsed(args), self.all_opts)

        self.succeess_lis = SuccessList()
        self.fail_lis = FailList()

    @property
    def desc_doc(self):
        doc = '''
        Usage: ab [options] [http[s]://]hostname[:port]/path
        Options are:
            -n requests     Number of requests to perform
            -c concurrency  Number of multiple requests to make at a time
            -t timelimit    Seconds to max. to spend on benchmarking
                            This implies -n 50000
            -s timeout      Seconds to max. wait for each response
                            Default is 30 seconds
            -b windowsize   Size of TCP send/receive buffer, in bytes
            -B address      Address to bind to when making outgoing connections
            -p postfile     File containing data to POST. Remember also to set -T
            -u putfile      File containing data to PUT. Remember also to set -T
            -T content-type Content-type header to use for POST/PUT data, eg.
                            'application/x-www-form-urlencoded'
                            Default is 'text/plain'
            -v verbosity    How much troubleshooting info to print
            -w              Print out results in HTML tables
            -i              Use HEAD instead of GET
            -x attributes   String to insert as table attributes
            -y attributes   String to insert as tr attributes
            -z attributes   String to insert as td or th attributes
            -C attribute    Add cookie, eg. 'Apache=1234'. (repeatable)
            -H attribute    Add Arbitrary header line, eg. 'Accept-Encoding: gzip'
                            Inserted after all normal header lines. (repeatable)
            -A attribute    Add Basic WWW Authentication, the attributes
                            are a colon separated username and password.
            -P attribute    Add Basic Proxy Authentication, the attributes
                            are a colon separated username and password.
            -X proxy:port   Proxyserver and port number to use
            -V              Print version number and exit
            -k              Use HTTP KeepAlive feature
            -d              Do not show percentiles served table.
            -S              Do not show confidence estimators and warnings.
            -q              Do not show progress when doing more than 150 requests
            -l              Accept variable document length (use this for dynamic pages)
            -g filename     Output collected data to gnuplot format file.
            -e filename     Output CSV file with percentages served
            -r              Don't exit on socket receive errors.
            -m method       Method name
            -h              Display usage information (this message)
            -Z ciphersuite  Specify SSL/TLS cipher suite (See openssl ciphers)
            -f protocol     Specify SSL/TLS protocol
                            (SSL2, SSL3, TLS1 or ALL)'''
        return "\n".join([line[8:] for line in doc.split('\n')][1:])

    @property
    def all_opts(self):
        desc = self.desc_doc
        opts = set()
        for line in desc.split('\n'):
            line = line.strip()
            if line.startswith('-'):
                opt = line.split(' ', 1)[0][1:]
                opts.add(opt)
        return opts

    def args_parsed(self, args):
        '''get opts string from args, and return it'''
        args = args.strip()
        if not args:
            print 'ab: need args.'
            self._V()
            self._h()
            exit()

        # quit if opts contain V(version) or h(help)
        pos1 = args.find('-V')
        pos2 = args.find('-h')
        if pos1 == -1 and pos2 == -1:
            pass
        elif pos1 == -1 and pos2 != -1:
            self._h()
            exit()
        elif pos1 != -1 and pos2 == -1:
            self._V()
            exit()
        else:
            self._h() if pos1 > pos2 else self.http_version
            exit()

        # must be contain [http[s]://]hostname[:port]/path, otherwise invalid URL
        pos = args.strip().rfind(' ')
        if pos == -1:
            opts, url = '', args
        else:
            opts, url = args[:pos + 1], args[pos + 1:].strip()
        res = re.match(r'((?P<protocal>https?)://)?(?P<hostname>[\w\.]*?)(:(?P<port>\d{1,5}))?(?P<path>/.*)', url)
        if not res:
            print 'ab: invalid URL'
            self._V()
            self._h()
            exit()
        if res.group('protocal'):
            self.protocal = res.group('protocal')
        self.hostname = res.group('hostname')
        if res.group('port'):
            self.port = long(res.group('port'))
        self.path = res.group('path')
        self.header['Host'] = '%s:%d' % (self.hostname, self.port)

        if len(opts.strip()) > 0 and '-' not in opts:
            print 'ab: wrong number of arguments'
            self._V()
            self._h()
            exit(0)

        return opts

    def one_request(self, q_args, out_put):
        '''
        q_args=Queue()
        when q_args get a tuple(group, userid), Start
        When q_args get a 'EOF' string, Quit
        Otherwise block within that time
        '''

        def get_new_connection():
            sock = SocketHandle()
            sock.apr_time_init()
            sock.connect(self.hostname, self.port)
            sock.modify_windowsize(self.windowsize)
            return sock

        request_text = self.request.request_text
        sock = None
        while True:
            try:
                ele = q_args.get(timeout=5 * 60)
            except Empty:
                break

            if ele == 'EOF':
                break
            else:
                group, user_id = ele

            try:
                if sock is None:
                    sock = get_new_connection()
                sock.send(request_text)
                response = Response(sock.recv())
                # only record one of the succeed responses
                if self.response is None and 200 <= response.status_code < 300:
                    self.response = response
                self.succeess_lis.add(group, sock.apr_time, response)
                if not self.keep_alive:
                    sock.quit()
                    sock = None
                else:
                    sock.apr_time_init()
            except socket.error, e:
                try:
                    sock.quit()
                except:
                    pass
                sock = None  # last connection error . so need to connect again
                self.fail_lis.add(group, 'socket_error')
            except Exception, e:
                self.fail_lis.add(group, 'other_error')
            finally:
                out_put.put(ele)
        if sock:
            sock.quit()

    def concurrency_request(self):
        q_args = Queue()
        out_put = Queue()
        threads_polls = []
        for user_id in xrange(self.concurrency_users):
            request_thread = Thread(target=self.one_request, args=(q_args, out_put))
            request_thread.setDaemon(True)
            threads_polls.append(request_thread)
        for th in threads_polls: th.start()
        return threads_polls, q_args, out_put

    def start(self):
        for opt in self._opts:
            getattr(self, '_%s' % opt, self.null)(opt)
        self.request = Request(self.header, self.data, self.method, self.path, self.http_version, self.protocal)
        self._V()
        print "Benchmarking %s (be patient)" % self.hostname,

        threads_polls, q_args, out_put = self.concurrency_request()
        begin = datetime.now()
        for group in xrange(1, self.number_of_requests + 1, self.concurrency_users):
            out_i = 0
            if (datetime.now() - begin).total_seconds() > self.max_seconds:
                break
            remained = self.number_of_requests - group + 1
            concurrency_users = min(self.concurrency_users, remained)
            for users_id in xrange(concurrency_users):
                q_args.put((group, users_id))
            try:
                while out_i != concurrency_users:
                    out_put.get()
                    self.bar(group + out_i, self.number_of_requests)
                    out_i += 1
            except KeyboardInterrupt:
                exit()
        if self.concurrency_users > 1:
            self.succeess_lis.time_taked = (datetime.now() - begin).total_seconds()

        for j in xrange(self.concurrency_users):
            q_args.put('EOF')
        for th in threads_polls:
            th.join()

        print 'Finished %d requests\n\n' % (self.succeess_lis.total + self.fail_lis.total)
        self.output()

    def bar(self, i, count):
        if getattr(self, 'quite', False):
            return
        i, count = long(i), long(count)
        if count > 150:
            base_num = 10 ** (len(str(count - 1)) - 1)
            if i == 1:
                print ''
            if i % base_num == 0:
                print 'Completed %d requests' % i
        else:
            base1, base2, base3, base4, base5 = count * 1 / 5 or 1, count * 2 / 5 or 1, count * 3 / 5 or 1, count * 4 / 5 or 1, count
            if i == base1: print '.',
            if i == base2: print '.',
            if i == base3: print '.',
            if i == base4: print '.',
            if i == base5: print '.done\n\n'

    def output(self):
        request, response = self.request, self.response
        if response is None:
            response = Response('')
        if self.verbosity >= 2:
            print 'LOG -- Request Status'
            print request.request_status_line
            print 'LOG -- Request Headers'
            print request.request_header, '\n'
            if self.verbosity >= 3:
                print 'LOG --- Response Status'
                print response.status_line
                print 'LOG --- Response Headers'
                print response.origin_header, '\n'
                if self.verbosity >= 4:
                    print 'LOG --- Body Received:'
                    print response.body, '\n'

        print '%-20s %s' % ('Server Software:', response.header.get('Server', 'unknown'))
        print '%-20s %s' % ('Server Hostname:', self.hostname)
        print '%-20s %d\n\n' % ('Server Port:', self.port)

        print '%-20s %s' % ('Document Path:', self.path)
        print '%-20s %s bytes\n\n' % ('Document Length:', response.len_of_body)

        suc, fai = self.succeess_lis, self.fail_lis

        print '%-20s %s' % ('Concurrency Level:', self.concurrency_users)
        print '%-20s %.3f' % ('Time taken for tests:', suc.time_taked)
        print '%-20s %d' % ('Complete requests:', suc.total + fai.total)
        print '%-20s %d' % ('Failed requests:', fai.total)
        if fai.total > 0:
            print '' * 5, '(Connect: %d, Length: %d, Exceptions: %d)' % \
                          (fai.connect_error_total, fai.length_error_total, fai.exceptions_error_total)
        print '%-20s %s bytes' % ('Total transferred:', suc.total_transferred)
        print '%-20s %s bytes' % ('HTML transferred:', suc.body_transferred)

        print '%-20s %.2f [#/sec] (mean)' % ('Requests per second:', suc.requests_per_second)
        print '%-20s %.3f [ms] (mean)' % ('Time per request:', suc.time_per_request_for_user)
        print '%-20s %.3f [ms] (mean, across all concurrent requests)' % \
              ('Time per request:', suc.time_per_request_for_server)
        print '%-20s %.2f [Kbytes/sec] received\n' % ('Transfer rate:', suc.transfer_rate)

        if suc.total >= 1:
            print 'Connection Times (ms)'
            print '%-15s %6s %6s %8s %8s %6s' % ('', 'min', 'mean', '[+/-sd]', 'median', 'max')
            template = '%-15s %6d %6d %8.1f %8d %6d'
            print template % (('Connect:',) + suc.analyze('Connect'))
            print template % (('Processing:',) + suc.analyze('Processing'))
            print template % (('Waiting:',) + suc.analyze('Waiting'))
            print template % (('Total:',) + suc.analyze('Total'))
            print

        if self.number_of_requests > 1 and suc.total >= 1:
            # apr_time = info[1]
            temp = [info[1].total for info in suc]
            temp.sort()
            print 'Percentage of the requests served within a certain time (ms)'
            template = '%5d%%%10d'
            percents = [0.5, 0.66, 0.75, 0.8, 0.9, 0.95, 0.98, 0.99, 1]
            for percent in percents:
                has_completed = int(suc.total * percent)
                if percent != 1:
                    print template % (percent * 100, temp[has_completed - 1] * 1000)
                else:
                    print template % (percent * 100, temp[has_completed - 1] * 1000), '(longest request)'

    def null(self, opt):
        warn_info = 'opts -%s has been deprecated, has not been implemented in ab' % opt
        warnings.warn(warn_info)

    def opt_error(self, opt):
        print 'ab: -%s args error' % opt
        self._h('h')
        exit()

    def _A(self, opt='A'):
        a_str = self._opts.get(opt)
        if a_str is None:
            self.opt_error(opt)
        b64_str = base64.b64encode(a_str)
        self.header['Authorization'] = 'Basic %s' % b64_str

    def _b(self, opt='b'):
        try:
            self.windowsize = long(self._opts[opt])
        except:
            self.opt_error(opt)

    def _c(self, opt='c'):
        if self._opts.has_key('n'):
            self._n('n')
        try:
            self.concurrency_users = long(self._opts.get(opt))
        except:
            self.opt_error(opt)

        if self.concurrency_users > self.number_of_requests:
            print "ab: Cannot use concurrency level greater than total number of requests"
            self._h()
            exit()

    def _C(self, opt='C'):
        cookies = self._opts.get(opt)
        if cookies is None:
            self.opt_error(opt)
        self.header['Cookies'] = cookies

    def _h(self, opt='h'):
        print self.desc_doc

    def _H(self, opt='H'):
        custom_header = {}
        header_str = self._opts.get(opt)
        if header_str is None:
            self.opt_error(opt)
        for one_header in header_str.split(';'):
            name, value = tuple(one_header.split(':', 1))
            custom_header[name.strip()] = value.strip()
        self.header.update(custom_header)

    def _i(self, opt='i'):
        self.method = 'HEAD'

    def _k(self, opt='k'):
        self.header['Connection'] = 'keep-alive'
        self.keep_alive = True

    def _m(self, opt='m'):
        try:
            self.method = self._opts.get(opt).upper()
        except:
            self.opt_error(opt)

    def _n(self, opt='n'):
        try:
            self.number_of_requests = long(self._opts.get(opt))
        except:
            self.opt_error(opt)

    def _p(self, opt='p'):
        file = self._opts.get(opt)
        if file is None:
            self.opt_error(opt)
        if os.path.isfile(file):
            with open(file, 'r+') as f:
                postdata = f.read().strip()
                self.method = 'POST'
                self.header['Content-Length'] = len(postdata)
                self.request.data = self.data = postdata
        else:
            raise ValueError('%s is not exists' % file)

    def _P(self, opt='P'):
        p_str = self._opts.get(opt)
        if p_str is None:
            self.opt_error(opt)
        b64_str = base64.b64encode(p_str)
        self.header['Proxy-Authorization'] = 'Basic %s' % b64_str

    def _q(self, opt='q'):
        self.quite = True

    def _s(self, opt='s'):
        try:
            self.timeout = long(self._opts.get(opt))
        except:
            self.opt_error(opt)

    def _t(self, opt='t'):
        try:
            self.max_seconds = long(self._opts.get(opt))
        except:
            self.opt_error(opt)
        if self.max_seconds <= 0:
            self.opt_error(opt)

    def _T(self, opt='T'):
        content_type = self._opts.get(opt)
        if not content_type:
            content_type = 'text/plain'
        self.header['Content-Type'] = content_type

    def _v(self, opt='v'):
        try:
            self.verbosity = int(self._opts.get(opt))
        except:
            self.opt_error(opt)

    def _V(self, opt='V'):
        desc = '''
        This is ApacheBench, Version %s . Written in python2.7+
        Copyright 2016 Lqe, http://www.zeustech.net/ ''' % Ab.VERSION
        print '\n'.join([line[8:] for line in desc.split('\n')])

    def _X(self, opt='X'):
        temp = self._opts.get('X').split(':')
        self.path = '%s:%s%s' % (self.hostname, self.port, self.path)
        self.hostname = temp[0].strip()
        self.port = 80
        if len(temp) == 2:
            try:
                self.port = long(temp[1].strip())
            except:
                self.opt_error(opt)


class Opts(dict):
    def __init__(self, opts, all_opts=None):
        super(Opts, self).__init__()
        self.origin_opts = opts
        self.all_opts = all_opts
        self.opts_parsed(opts)

    def opts_parsed(self, opts):
        res = re.split(r'(-\w )', opts)
        for i in xrange(len(res)):
            if not res[i].startswith('-'):
                continue

            opt = '%s' % res[i][1:].strip()
            if opt not in self.all_opts:
                continue

            if not res[i + 1].startswith('-'):
                name, value = opt, res[i + 1].strip().strip("\'\"")
            else:
                name, value = opt, None

            if not self.has_key(name):
                self[name] = value
            else:
                if name in ['C', 'H']:  # can repeat
                    self[name] = '%s; %s' % (self[name], value)
                else:
                    self[name] = value

            # quit if opts contain V(version) or h(help)
            if self.has_key('V') or self.has_key('h'):
                return


class SuccessList(list):
    def __init__(self, ):
        super(SuccessList, self).__init__()
        self.total = 0
        self.total_transferred = 0
        self.body_transferred = 0
        self.time_taked = 0
        self.lock = Lock()

    def add(self, group, apr_time, response):
        self.lock.acquire()
        self.total += 1
        self.time_taked += apr_time.total
        self.total_transferred += response.len_of_text
        self.body_transferred += response.len_of_body
        self.append((group, apr_time))
        self.lock.release()

    @property
    def groups(self):
        return len(set(info[0] for info in self))

    @property
    def requests_per_second(self):
        time_taked = self.time_taked
        if time_taked > 0:
            return self.total / time_taked
        else:
            return 0

    @property
    def time_per_request_for_user(self):
        groups = self.groups
        if groups > 0:
            return self.time_taked * 1000 / groups
        else:
            return 0

    @property
    def time_per_request_for_server(self):
        if self.time_taked > 0:
            return self.time_taked * 1000 / self.total
        else:
            return 0

    @property
    def transfer_rate(self):
        if self.time_taked != 0:
            return self.total_transferred / (1024 * self.time_taked)
        else:
            return 0

    def analyze(self, type=None):
        if type in ['Connect', 'Processing', 'Waiting', 'Total']:
            type = type.lower()
            lis = [getattr(info[1], type) * 1000 for info in self]
            c = Calc([t for t in lis if t > 0])
            return c.min(), c.avg(), c.variance(), c.median(), c.max()


class FailList(list):
    def __init__(self, ):
        super(FailList, self).__init__()
        self.total = 0
        self.connect_error_total = 0
        self.length_error_total = 0
        self.exceptions_error_total = 0
        self.lock = Lock()

    def add(self, group, desc):
        self.lock.acquire()
        self.total += 1
        if desc == 'socket_error':
            self.connect_error_total += 1
        elif desc == 'length_error':
            self.length_error_total += 1
        else:
            self.exceptions_error_total += 1
        self.append((group, desc))
        self.lock.release()


if __name__ == '__main__':
    Ab(' '.join(sys.argv[1:]).strip()).start()

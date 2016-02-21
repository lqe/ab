from datetime import datetime
import StringIO
import gzip


def gzip_decode(content):
    compressedstream = StringIO.StringIO(content)
    gzipper = gzip.GzipFile(fileobj=compressedstream)
    return gzipper.read()


def chunked_decode(content):
    pos = content.find('\r\n')
    readbytes = int(content[0:pos], 16)
    offset = pos + 2
    newcontent = ''
    while (readbytes > 0):
        newcontent += content[offset:offset + readbytes]
        offset += readbytes + 2
        pos = content.find('\r\n', offset)
        if pos > -1:
            readbytes = int(content[offset:pos], 16)
            if readbytes == 0:
                break
            else:
                offset = pos + 2
    return newcontent


def time_test(fun):
    def _wrapper(*args, **kwargs):
        begin = datetime.now()
        res = fun(*args, **kwargs)
        return res, datetime.now() - begin

    return _wrapper


class Calc:
    def __init__(self, sequence):
        # sequence of numbers we will process
        # convert all items to floats for numerical processing
        self.sequence = [float(item) for item in sequence]

    def min(self):
        if len(self.sequence) < 1:
            return None
        else:
            return min(self.sequence)

    def max(self):
        if len(self.sequence) < 1:
            return None
        else:
            return max(self.sequence)

    def avg(self):
        if len(self.sequence) < 1:
            return None
        else:
            return sum(self.sequence) / len(self.sequence)

    def median(self):
        if len(self.sequence) < 1:
            return None
        else:
            self.sequence.sort()
            return self.sequence[len(self.sequence) // 2]

    def variance(self):
        if len(self.sequence) < 1:
            return None
        else:
            avg = self.avg()
            sdsq = sum([(i - avg) ** 2 for i in self.sequence])
            return sdsq / len(self.sequence)


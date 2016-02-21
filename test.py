from ab import Ab

args = {
    -1: "%s",
    0: "-A auth-username:password -b 1024 %s",
    1: "-h %s",
    2: "-V %s",
    3: "-n 80 -c 80 %s",
    4: "-v 3 -C name1=Value1 -C name2=Value2 -H 'Accept-Encoding:gzip, deflate' -H Accept: text/html %s",
    5: "-v 5 -X 127.0.0.1:8000  %s",
    6: "-v 5 %s",
    7: "-n 200  -c 4  %s",
    8: "-n 880 -c 10 -q %s",
    9: "-v 5 -i %s",
    10: "-n 2 -k %s",
    11: "-v 2 -T %s",
    12: "-n 800 -t 5 %s",
    13: "-v 5 -T 'application/x-www-form-urlencoded' -p /Users/lqe/Desktop/postdata.txt %s",
    14: "-u put_file %s"
}
urls = {
    0 : 'http://127.0.0.1:23456/',
    1 : 'http://127.0.0.1:8000/',
    2 : 'http://www.weehua.cn/',
    3 : 'http://www.baidu.com/'
}

if __name__ == '__main__':
    Ab(args[7] % urls[3]).start()
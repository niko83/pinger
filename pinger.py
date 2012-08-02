#!/usr/bin/env python
#-*- coding: utf-8 -*-
import os
import re
import urllib2
import urllib
import contextlib
import sys
from Queue import Queue
from threading import Thread
import time

from config import HOST, PATH_TO_NGINX_ACCESS_LOG, PATH_TO_LOG, COUNT_LATEST_BITES, \
        COUNT_THREADING, PRINT_STATUS_COUNT, FAKE_SUBSTR, DJANGO_ADMIN_LOGIN, DJANGO_ADMIN_PASSWORD

class PingerException(Exception):
    pass

COLORS = {
    'reset' : "\x1b[0m",
    'green':"\x1b[32;01m",
    'red':"\x1b[31;01m"
}

class Counters(object):
    startTime = ''
    uriForChecking = 0
    error5xx  = 0
    error4xx = 0
    errorOther = 0

def main():

    os.system('clear')
    logging ('{:<20}:{:s}'.format('Testing host', HOST))

    if not os.path.exists(PATH_TO_LOG):
        logging('Error: path to logs "%s" not found!!!\n' % PATH_TO_LOG, 'red')
        return
    if not os.path.exists(PATH_TO_NGINX_ACCESS_LOG):
        logging('Error: path to nginx access log "%s" not found!!!\n' % PATH_TO_NGINX_ACCESS_LOG, 'red')
        return

    logging('{:<20}:{:s} ({:.2f} Mb from {:.2f} Mb)'.format(
            'Parsing log file',
            PATH_TO_NGINX_ACCESS_LOG,
            COUNT_LATEST_BITES/(1024*1024)\
                    if COUNT_LATEST_BITES  and (os.path.getsize(PATH_TO_NGINX_ACCESS_LOG) > COUNT_LATEST_BITES) \
                    else os.path.getsize(PATH_TO_NGINX_ACCESS_LOG)/(1024*1024),
            os.path.getsize(PATH_TO_NGINX_ACCESS_LOG)/(1024*1024)
            ))
    uriForChecking = getUriesFromFile(PATH_TO_NGINX_ACCESS_LOG)
    logging('{:<20}:{:d}'.format('Found unique uri', len(uriForChecking)))

    setDjangoAdminLogin()

    enclosure_queue = Queue()
    for uri in uriForChecking:
        enclosure_queue.put(uri)

    Counters.startTime = time.time()
    Counters.uriForChecking = len(uriForChecking)

    for i in range(COUNT_THREADING):
        worker = Thread(target=processingUriQueue, args=(enclosure_queue,))
        worker.setDaemon(True)
        worker.start()

    enclosure_queue.join()

    if PATH_TO_LOG.startswith('/'):
        ABS_PATH_TO_LOG = PATH_TO_LOG
    else:
        ABS_PATH_TO_LOG = ''.join([os.path.dirname(os.path.abspath(__file__)), '/', PATH_TO_LOG])
    print ""
    logging('Done. More logs here: ' + ABS_PATH_TO_LOG ,'green')

def logging(text, color='reset', flush = False):
    br = '' if flush else '\n'
    sys.stdout.write(''.join([COLORS[color], text, COLORS['reset'],  " "* (80-len(text)), '\r', br]))
    sys.stdout.flush()

def setDjangoAdminLogin():
    logging('{:<20}:{:s}'.format('Login to admin:', 'Processing...'), flush = True)

    try:
        login_url = HOST+'/admin/'

        cookies = urllib2.HTTPCookieProcessor()
        opener = urllib2.build_opener(cookies)
        urllib2.install_opener(opener)

        try:
            opener.open(login_url)
        except:
            raise PingerException("ERROR, %s is't open" % login_url)

        try:
            token = [x.value for x in cookies.cookiejar if x.name == 'crsf_cookie'][0]
        except IndexError:
            raise PingerException("ERROR, no csrftoken")

        params = dict(
            username = DJANGO_ADMIN_LOGIN,
            password = DJANGO_ADMIN_PASSWORD,
            this_is_the_login_form=True,
            csrfmiddlewaretoken=token,
            next='/admin/'
        )

        encoded_params = urllib.urlencode(params)

        with contextlib.closing(opener.open(login_url, encoded_params)) as f:
            response = f.read()
        if 'id="login-form"' in response:
            raise PingerException('Wrong login or password')
    except PingerException as error:
        djangoAdminMessage = ''.join([COLORS['red'], str(error), COLORS['reset']])
    else:
        djangoAdminMessage = 'OK'
    logging('{:<20}:{:s}'.format('Login to admin:', djangoAdminMessage))


def getUriesFromFile(path_to_file):
    log_file = open(path_to_file, 'r')
    try:
        if COUNT_LATEST_BITES and (os.path.getsize(PATH_TO_NGINX_ACCESS_LOG) > COUNT_LATEST_BITES):
            log_file.seek(-COUNT_LATEST_BITES, 2)
        lines = True
        uriForChecking = set()
        while lines:
            count_symbols_in_part = 50000000
            lines = log_file.readlines(count_symbols_in_part)
            for line in lines:
                if isFakeRequest(line):
                    continue

                uri = getUriFromLine(line)
                if uri:
                    uriForChecking.add(uri)
    finally:
        log_file.close()

    return uriForChecking

def getUriFromLine(line):
    url_match = re.match(r'.*"(GET|HEAD)\s([^\s]*)\s.*', line)
    if url_match:
        return url_match.group(2)
    return False


def processingUriQueue(queue):
    while True:
        uri = queue.get()
        checkUri(uri)
        queue.task_done()
        qsize = queue.qsize()
        if qsize % PRINT_STATUS_COUNT == 0:
            executTimeOneRequest = (time.time() - Counters.startTime)/(Counters.uriForChecking - qsize)
            leftTime = qsize * executTimeOneRequest

            leftTime_hour = int(leftTime / 3600)
            leftTime_min  = int((leftTime - leftTime_hour*3600)/ 60)
            leftTime_sec  = int(leftTime-leftTime_min*60 - leftTime_hour*3600)

            logging  ('Left parsing {:>7d} urls (time left {:0>3d}:{:0>2d}:{:0>2d}). Avg. time response: {:d} ms. Errors 5xx:{:d} 4xx:{:d} Other:{:d}'\
                    .format(qsize , leftTime_hour, leftTime_min, leftTime_sec, int(executTimeOneRequest * 1000),Counters.error5xx , Counters.error4xx, Counters.errorOther), flush=True)


def checkUri(uri):
    url = HOST+uri

    try:
        request = urllib2.Request(url)
        request.get_method = lambda : 'HEAD'
        urllib2.urlopen(request)
        log_file_name = 'ok'
        message = '%s' % url
    except urllib2.HTTPError as error:
        log_file_name = getErrorFilename(error)

        if 400 <= int(error.code) < 500:
            Counters.error4xx += 1
        elif 500 <= int(error.code) < 600:
            Counters.error5xx += 1
        else:
            Counters.errorOther += 1
        message = '%s - %s' % (error, url)
    except Exception as error:
        Counters.errorOther += 1
        log_file_name = getErrorFilename(error)
        message = '%s - %s' % (error, url)

    try:
        logging_file = open(PATH_TO_LOG+log_file_name, 'a')
        logging_file.write('\n'+message)
    finally:
        logging_file.close()


def getErrorFilename(error):
    file_name = str(error)
    file_name = file_name.lower()
    file_name = re.sub('[^\w]', '_', file_name)
    file_name = file_name if file_name else 'unknown_error'
    return file_name


def isFakeRequest(line):
    for segment in FAKE_SUBSTR:
        if segment in line:
            return True


if __name__ == "__main__":
    main()

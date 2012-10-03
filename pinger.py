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
import subprocess

from selenium import webdriver

from config import HOST, HOST_COMPARE_SREEN, PATH_TO_NGINX_ACCESS_LOG,\
                   PATH_TO_LOG,\
                   COUNT_LATEST_BITES, COUNT_THREADING, PRINT_STATUS_COUNT,\
                   FAKE_SUBSTR, DJANGO_ADMIN_LOGIN, DJANGO_ADMIN_PASSWORD,\
                   HOST_COMPARE_SREEN

COUNT_LATEST_MBITES = COUNT_LATEST_BITES / (1024 * 1024)

COLORS = {
    'reset': "\x1b[0m",
    'green': "\x1b[32;01m",
    'red': "\x1b[31;01m"
}
FIREFOX = 'firefox'
CHROME = 'chrome'
BROWSERS = {
    FIREFOX: webdriver.Firefox(),
    # CHROME: webdriver.Chrome()
}


class PingerException(Exception):
    pass


class Counters(object):
    startTime = ''
    uri_for_checking = 0
    error5xx = 0
    error4xx = 0
    errorOther = 0


def get_file_size_mb(path):
    return os.path.getsize(path) / (1024 * 1024)


def main():

    os.system('clear')
    logging('{:<20}:{:s}'.format('Testing host', HOST))

    if not os.path.exists(PATH_TO_LOG):
        logging('Error: path to logs "%s" not found!!!\n' % PATH_TO_LOG, 'red')
        return
    if not os.path.exists(PATH_TO_NGINX_ACCESS_LOG):
        logging('Error: path to nginx access log "%s" not found!!!\n' % PATH_TO_NGINX_ACCESS_LOG, 'red')
        return

    if COUNT_LATEST_MBITES and (get_file_size_mb(PATH_TO_NGINX_ACCESS_LOG) > COUNT_LATEST_MBITES):
        analized_fragment = COUNT_LATEST_MBITES
    else:
        analized_fragment = get_file_size_mb(PATH_TO_NGINX_ACCESS_LOG)

    logging('{:<20}:{:s} ({:.2f} Mb from {:.2f} Mb)'.format(
            'Parsing log file', PATH_TO_NGINX_ACCESS_LOG,
            analized_fragment,
            get_file_size_mb(PATH_TO_NGINX_ACCESS_LOG)
            ))
    uri_for_checking = getUriesFromFile(PATH_TO_NGINX_ACCESS_LOG)
    logging('{:<20}:{:d}'.format('Found unique uri', len(uri_for_checking)))

    set_django_admin_login()

    enclosure_queue = Queue()
    for uri in uri_for_checking:
        enclosure_queue.put(uri)

    Counters.startTime = time.time()
    Counters.uri_for_checking = len(uri_for_checking)

    for i in range(COUNT_THREADING):
        worker = Thread(target=processing_uri_queue, args=(enclosure_queue,))
        worker.setDaemon(True)
        worker.start()

    enclosure_queue.join()

    if PATH_TO_LOG.startswith('/'):
        ABS_PATH_TO_LOG = PATH_TO_LOG
    else:
        ABS_PATH_TO_LOG = ''.join([os.path.dirname(os.path.abspath(__file__)), '/', PATH_TO_LOG])
    print ""
    logging('Done. More logs here: ' + ABS_PATH_TO_LOG, 'green')


def logging(text, color='reset', flush=False):
    br = '' if flush else '\n'
    sys.stdout.write(''.join([COLORS[color], text, COLORS['reset'],  " " * (80 - len(text)), '\r', br]))
    sys.stdout.flush()


def set_django_admin_login():
    logging('{:<20}:{:s}'.format('Login to admin:', 'Processing...'), flush=True)

    try:
        login_url = HOST + '/admin/'
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
            username=DJANGO_ADMIN_LOGIN,
            password=DJANGO_ADMIN_PASSWORD,
            this_is_the_login_form=True,
            csrfmiddlewaretoken=token,
            next='/admin/'
        )

        encoded_params = urllib.urlencode(params)

        try:
            with contextlib.closing(opener.open(login_url, encoded_params)) as f:
                response = f.read()
        except urllib2.HTTPError as error:
            raise PingerException(error)

        if 'id="login-form"' in response:
            raise PingerException('Wrong login or password')
    except PingerException as error:
        django_admin_message = ''.join([COLORS['red'], str(error), COLORS['reset']])
    else:
        django_admin_message = 'OK'
    logging('{:<20}:{:s}'.format('Login to admin:', django_admin_message))


def getUriesFromFile(path_to_file):
    log_file = open(path_to_file, 'r')
    try:
        if COUNT_LATEST_BITES and (os.path.getsize(PATH_TO_NGINX_ACCESS_LOG) > COUNT_LATEST_BITES):
            log_file.seek(-COUNT_LATEST_BITES, 2)
        lines = True
        uri_for_checking = set()
        while lines:
            count_symbols_in_part = 50000000
            lines = log_file.readlines(count_symbols_in_part)
            for line in lines:
                if is_fake_request(line):
                    continue

                uri = get_uri_from_line(line)
                if uri:
                    uri_for_checking.add(uri)
    finally:
        log_file.close()

    return uri_for_checking


def get_uri_from_line(line):
    url_match = re.match(r'.*"(GET|HEAD)\s([^\s]*)\s.*', line)
    if url_match:
        return url_match.group(2)
    return False


def processing_uri_queue(queue):
    while True:
        uri = queue.get()
        check_uri(uri)
        queue.task_done()
        qsize = queue.qsize()
        if qsize % PRINT_STATUS_COUNT == 0:
            executTimeOneRequest = (time.time() - Counters.startTime) / (Counters.uri_for_checking - qsize)
            leftTime = qsize * executTimeOneRequest

            leftTime_hour = int(leftTime / 3600)
            leftTime_min = int((leftTime - leftTime_hour * 3600) / 60)
            leftTime_sec = int(leftTime - leftTime_min * 60 - leftTime_hour * 3600)

            logging('Left parsing {:>7d} urls (time left {:0>3d}:{:0>2d}:{:0>2d}). Avg. time response: {:d} ms. Errors 5xx:{:d} 4xx:{:d} Other:{:d}'
                    .format(qsize, leftTime_hour, leftTime_min, leftTime_sec, int(executTimeOneRequest * 1000),
                            Counters.error5xx, Counters.error4xx, Counters.errorOther), flush=True)


def check_uri(uri):
    url = HOST + uri

    try:
        request = urllib2.Request(url)
        request.get_method = lambda: 'HEAD'
        urllib2.urlopen(request)
        log_file_name = 'ok'
        message = '%s' % url
        screen(uri)
    except urllib2.HTTPError as error:
        log_file_name = get_error_filename(error)

        if 400 <= int(error.code) < 500:
            Counters.error4xx += 1
        elif 500 <= int(error.code) < 600:
            Counters.error5xx += 1
        else:
            Counters.errorOther += 1
        message = '%s - %s' % (error, url)
    except Exception as error:
        Counters.errorOther += 1
        log_file_name = get_error_filename(error)
        message = '%s - %s' % (error, url)

    try:
        logging_file = open(PATH_TO_LOG + log_file_name, 'a')
        logging_file.write('\n' + message)
    finally:
        logging_file.close()



def get_error_filename(error):
    file_name = str(error)
    file_name = file_name.lower()
    file_name = re.sub('[^\w]', '_', file_name)
    file_name = file_name if file_name else 'unknown_error'
    return file_name


def is_fake_request(line):
    for segment in FAKE_SUBSTR:
        if segment in line:
            return True


def screen(uri):
    browser = BROWSERS[FIREFOX]

    time_sleep = 0.5
    url = HOST + uri
    browser.get(url)
    time.sleep(time_sleep)
    path_one = PATH_TO_LOG + get_error_filename(url)
    browser.save_screenshot(path_one)

    url = HOST_COMPARE_SREEN + uri
    browser.get(url)
    time.sleep(time_sleep)
    path_two = PATH_TO_LOG + get_error_filename(url)
    browser.save_screenshot(path_two)

    path_diff = PATH_TO_LOG + get_error_filename(uri) + '.png'
    response = subprocess.check_output(['compare',
                                        '-metric', 'PSNR',
                                        path_one, path_two,
                                        '-highlight-color red',
                                        path_diff],
                                       stderr=subprocess.STDOUT)[:-1]
    os.remove(path_one)
    os.remove(path_two)
    if response == 'inf':
        os.remove(path_diff)
        path_diff = ''

    file_name = PATH_TO_LOG + 'screen'
    try:
        logging_file = open(file_name, 'a')
        logging_file.write('\n' + response + ' ' + uri + ' ' + path_diff)
    finally:
        logging_file.close()


if __name__ == "__main__":
    main()

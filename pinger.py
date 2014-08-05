# !/usr/bin/env python
# -*- coding: utf-8 -*-
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
import random

from selenium import webdriver

from config import (
    HOST, HOST_COMPARE_SREEN, PATH_TO_NGINX_ACCESS_LOG,
    PATH_TO_LOG, PATH_TO_SCREENS,
    COUNT_LATEST_BITES, COUNT_THREADING, PRINT_STATUS_COUNT,
    FAKE_SUBSTR, DJANGO_ADMIN_LOGIN, DJANGO_ADMIN_PASSWORD,
    IS_CHECK_UI,
)

COUNT_LATEST_MBITES = COUNT_LATEST_BITES / (1024 * 1024)
PATH_TO_LOG_SCREEN = PATH_TO_LOG + 'screen'

COLORS = {
    'reset': "\x1b[0m",
    'green': "\x1b[32;01m",
    'red': "\x1b[31;01m"
}

FIREFOX = 'firefox'
CHROME = 'chrome'

BROWSERS = []


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
        logging('Error: path to nginx access log "%s" not found!!!\n'
                % PATH_TO_NGINX_ACCESS_LOG, 'red')
        return

    if (
        COUNT_LATEST_MBITES
        and (get_file_size_mb(PATH_TO_NGINX_ACCESS_LOG) > COUNT_LATEST_MBITES)
    ):
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

    for _ in range(COUNT_THREADING):
        browser = webdriver.Firefox()
        BROWSERS.append(browser)

        worker = Thread(target=processing_uri_queue, args=(enclosure_queue, [browser]))
        worker.setDaemon(True)
        worker.start()

    enclosure_queue.join()

    for browser in BROWSERS:
        browser.quit()

    if PATH_TO_LOG.startswith('/'):
        ABS_PATH_TO_LOG = PATH_TO_LOG
    else:
        ABS_PATH_TO_LOG = ''.join([os.path.dirname(os.path.abspath(__file__)), '/', PATH_TO_LOG])
    print ""
    logging('Done. More logs here: ' + ABS_PATH_TO_LOG, 'green')


def logging(text, color='reset', flush=False):
    sys.stdout.write(
        ''.join([
            COLORS[color],
            text,
            COLORS['reset'],
            " " * (80 - len(text)), '\r',
            '' if flush else '\n',
        ])
    )
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
        if (
            COUNT_LATEST_BITES
            and (os.path.getsize(PATH_TO_NGINX_ACCESS_LOG) > COUNT_LATEST_BITES)
        ):
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


def processing_uri_queue(queue, browsers):
    while True:
        uri = queue.get()
        check_uri(uri, browsers)
        queue.task_done()
        qsize = queue.qsize()
        try:
            str(qsize)
        except:
            return

        if qsize % PRINT_STATUS_COUNT == 0:
            executTimeOneRequest = ((time.time() - Counters.startTime)
                                    / (Counters.uri_for_checking - qsize))
            leftTime = qsize * executTimeOneRequest

            leftTime_hour = int(leftTime / 3600)
            leftTime_min = int((leftTime - leftTime_hour * 3600) / 60)
            leftTime_sec = int(leftTime - leftTime_min * 60 - leftTime_hour * 3600)

            logging('Left parsing {:>7d} urls (time left {:0>3d}:{:0>2d}:{:0>2d}). '
                    'Avg. time response: {:d} ms. Errors 5xx:{:d} 4xx:{:d} Other:{:d}'
                    .format(qsize, leftTime_hour, leftTime_min, leftTime_sec,
                            int(executTimeOneRequest * 1000), Counters.error5xx, Counters.error4xx,
                            Counters.errorOther), flush=True)


def check_uri(uri, browsers):
    url = HOST + uri

    try:
        request = urllib2.Request(url)
        request.get_method = lambda: 'HEAD'
        urllib2.urlopen(request)
        log_file_name = 'ok'
        message = '%s' % url
        if IS_CHECK_UI:
            try:
                request = urllib2.Request(HOST_COMPARE_SREEN + uri)
                request.get_method = lambda: 'HEAD'
                urllib2.urlopen(request)
            except urllib2.HTTPError as error:
                write_to_screen_log(str(error), uri)
            else:
                for browser in browsers:
                    screen(uri, browser)
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
    if len(file_name) > 100:
        file_name = file_name[0:100]
    return file_name


def is_fake_request(line):
    for segment in FAKE_SUBSTR:
        if segment in line:
            return True


def _get_path_to_screen(path):
    return PATH_TO_SCREENS + get_error_filename(path) + '.png'


def get_compare_img(browser, uri, sleep=0, is_last=False):

    prefix = str(random.randint(10000000, 99999999))

    url = HOST + uri
    browser.delete_all_cookies()
    browser.get(url)
    time.sleep(sleep)
    path_one = _get_path_to_screen(prefix + '_1')
    browser.save_screenshot(path_one)

    url = HOST_COMPARE_SREEN + uri
    browser.delete_all_cookies()
    browser.get(url)
    time.sleep(sleep)
    path_two = _get_path_to_screen(prefix + '_2')
    browser.save_screenshot(path_two)

    try:
        response = subprocess.check_output([
            'compare', '-metric', 'AE', '-fuzz', '10%', path_one, path_two, '/dev/null'
        ], stderr=subprocess.STDOUT)[:-1]
    except subprocess.CalledProcessError as error:
        write_to_screen_log('999999', str(error), uri)
        response = '0'

    if not is_last:
        time.sleep(0.2)
        os.remove(path_one)
        os.remove(path_two)
        if response == '0':
            return True
        else:
            return False

    path_diff = ''
    if response != '0':
        path_diff = _get_path_to_screen(prefix + '_diff')
        os.system('compare %s %s -highlight-color red %s' % (path_one, path_two, path_diff))
    else:
        time.sleep(0.2)
        os.remove(path_one)
        os.remove(path_two)

    write_to_screen_log(response, uri, path_diff)


def write_to_screen_log(*arg):
    file_name = PATH_TO_LOG_SCREEN
    try:
        logging_file = open(file_name, 'a')
        logging_file.write('\n' + ''.join(arg))
    finally:
        logging_file.close()

def screen(uri, browser):
    if not get_compare_img(browser, uri):
        get_compare_img(browser, uri, 5, True)


if __name__ == "__main__":
    main()

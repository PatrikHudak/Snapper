#!/usr/bin/env python
# -*- coding: utf-8 -*-

import copy
import multiprocessing
import os
import shutil
import signal
import sys
from optparse import OptionParser
from uuid import uuid4

import requests
from jinja2 import Environment, FileSystemLoader
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

try:
    import SocketServer
except ImportError:
    # py3
    import socketserver as SocketServer

try:
    import SimpleHTTPServer
except ImportError:
    #py3
    import http.server as SimpleHTTPServer

templates_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'templates')
env = Environment(autoescape=True, loader=FileSystemLoader(templates_path))

def init_fs(outpath):
    outpath = os.path.join(outpath, 'output')
    imagesOutputPath = os.path.join(outpath, 'images')

    if not os.path.exists(outpath):
        os.makedirs(outpath)
    if not os.path.exists(imagesOutputPath):
        os.makedirs(imagesOutputPath)

def save_image(uri, file_name, driver):
    try:
        driver.get(uri)
        driver.save_screenshot(file_name)
        return True
    except (TimeoutException, ):
        return False

def host_reachable(host, timeout):
    headers = {'user-agent': 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML,like Gecko) Chrome/41.0.2228.0 Safari/537.36'}
    try:
        requests.get(host, timeout=timeout, verify=False, headers=headers)
    except (requests.exceptions.RequestException, ):
        return False
    return True

def host_worker(hostQueue, fileQueue, timeout, user_agent, verbose, http_only):
    dcap = dict(DesiredCapabilities.PHANTOMJS)
    dcap['phantomjs.page.settings.userAgent'] = user_agent
    dcap['accept_untrusted_certs'] = True

    driver = webdriver.PhantomJS(service_args=['--ignore-ssl-errors=true'], desired_capabilities=dcap)
    driver.set_window_size(1024, 768)
    driver.set_page_load_timeout(timeout)

    while(not hostQueue.empty()):
        host = hostQueue.get()
        if not http_only and not host.startswith('http://') and not host.startswith('https://'):
            tmp_queue = ['http://{}'.format(host), 'https://{}'.format(host)]
        elif http_only and not host.startswith('http://'):
            tmp_queue = ['http://{}'.format(host)]
        else:
            tmp_queue = [host]

        for current in tmp_queue:
            filename = os.path.join('output', 'images', '{}-{}.png'.format(host.replace('https://', '').replace('http://', ''), str(uuid4())))
            if verbose:
                print('[*] Fetching {}'.format(current))

            if host_reachable(current, timeout) and save_image(current, filename, driver):
                fileQueue.put({current: filename})
            elif verbose:
                print('[!] {} is unreachable or timed out'.format(current))

    driver.service.process.send_signal(signal.SIGTERM)
    driver.quit()

def capture_snaps(hosts, outpath, timeout=10, serve=False, port=8000, 
        verbose=True, numWorkers=1, user_agent="Mozilla/5.0 (Windows NT\
            6.1) AppleWebKit/537.36 (KHTML,like Gecko) Chrome/41.0.2228.\
            0 Safari/537.36", http_only=False, name=None):

    init_fs(outpath)

    subdomains = copy.copy(hosts)
    hostQueue = multiprocessing.Queue()
    fileQueue = multiprocessing.Queue()

    workers = []
    for host in hosts:
        hostQueue.put(host)

    for i in range(numWorkers):
        p = multiprocessing.Process(target=host_worker, args=(hostQueue, fileQueue, timeout, user_agent, verbose, http_only))
        workers.append(p)
        p.start()

    try:
        for worker in workers:
            worker.join()
    except KeyboardInterrupt:
        for worker in workers:
            worker.terminate()
            worker.join()
        sys.exit(1)

    setsOfSix = []
    count = 0
    hosts = {}
    webapps = []

    while(not fileQueue.empty()):
        if count == 6:
            try:
                setsOfSix.append(hosts.iteritems())
            except AttributeError:
                setsOfSix.append(hosts.items())
            hosts = {}
            count = 0

        temp = fileQueue.get()
        hosts.update(temp)
        webapps.append(temp.keys()[0])

    try:
        setsOfSix.append(hosts.iteritems())
    except AttributeError:
        setsOfSix.append(hosts.items())

    template = env.get_template('index.html')

    with open(os.path.join(outpath, 'output', 'index.html'), 'w') as outputFile:
        outputFile.write(template.render(setsOfSix=setsOfSix, subdomains=subdomains, webapps=webapps, name=name))

    if serve:
        os.chdir('output')
        Handler = SimpleHTTPServer.SimpleHTTPRequestHandler
        httpd = SocketServer.TCPServer(('127.0.0.1', PORT), Handler)
        print('Serving at port {}'.format(PORT))
        httpd.serve_forever()
    else:
        return True

if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option("-f", "--file", action="store", dest="filename",
                      help="Souce from input file", metavar="FILE")
    parser.add_option("-l", "--list", action="store", dest="list",
                      help="Source from commandline list")
    parser.add_option("-u", '--user-agent', action='store', 
                      dest="user_agent", type=str, 
                      default="Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML,\
                              like Gecko) Chrome/41.0.2228.0 Safari/537.36", 
                      help='The user agent used for requests')
    parser.add_option("-c", '--concurrency', action='store', 
                      dest="numWorkers", type=int, default=1, 
                      help='Number of cuncurrent processes')
    parser.add_option("-t", '--timeout', action='store', 
                      dest="timeout", type=int, default=10, 
                      help='Number of seconds to try to resolve')
    parser.add_option("-p", '--port', action='store', 
                      dest="port", type=int, default=8000, 
                      help='Port to run server on')
    parser.add_option("-v", action='store_true', dest="verbose",
                      help='Display console output for fetching each host')


    (options, args) = parser.parse_args()
    if options.filename:
        with open(options.filename, 'r') as inputFile:
            hosts = inputFile.readlines()
            hosts = map(lambda s: s.strip(), hosts)
    elif options.list:
        hosts = []
        for item in options.list.split(','):
            hosts.append(item.strip())
    else:
        print('invalid args')
        sys.exit(1)

    numWorkers = options.numWorkers
    timeout = options.timeout
    verbose = options.verbose
    PORT = options.port
    user_agent = options.user_agent

    capture_snaps(hosts, os.getcwd(), timeout, True, PORT, verbose,
            numWorkers, user_agent)

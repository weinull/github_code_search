#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# Date: 2019/03/11
# Author: weinull

import os
import re
import time
import base64
import logging
import urllib3
import requests
from bs4 import BeautifulSoup

urllib3.disable_warnings()

# log配置
log_format = '[%(asctime)s]-[%(levelname)s] - %(message)s'
time_format = '%Y-%m-%d %H:%M:%S'
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    datefmt=time_format,
    filename=time.strftime('search.log'),
    filemode='a'
)
# 配置log输出到console
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter(log_format, time_format))
logging.getLogger('').addHandler(console)


class GithubSearch(object):
    """
    需配置Github账号
    登录请调用login()

    实例化Class后可根据需要修改Class中的变量后再进行操作
    或者直接改代码后再运行

    包含关键字的文件会自动下载到配置的目录中
    按照对应项目路径保存

    如需对搜索到的文件数据进行自定义处理可以修改data_check函数
    下载文件时才会调用到data_check函数
    data_check函数返回True时才会保存该文件

    keyword: 默认为空,调用search_keyword时配置,最长128
    download_domain: 下载文件时需替换成RAW域名才能下载到文件
    sleep_time: 当请求受限时暂停的时间
    proxies: HTTP请求代理配置
    download_folder: 搜索到的文件保存目录
    download_flag: 是否下载保存搜索到的文件
    search_page_max: 最大搜索页数
    error_data_log: data_check函数出错时是否记录处理出错的数据,数据base64编码处理
    output_file: 自定义输出文件
    """

    def __init__(self):
        self.login_account = ''
        self.login_password = ''

        self.keyword = ''

        self.search_url = 'https://github.com/search?o=desc&q="{keyword}"+in:file&s=indexed&type=Code&p={page}'
        self.search_page_max = 100

        self.github_domain = 'https://github.com'
        self.download_domain = 'https://raw.githubusercontent.com'

        self.download_folder = './downloads'
        self.download_flag = True

        self.rq = requests.Session()
        self.timeout = 15
        self.sleep_time = 5
        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
                          ' Chrome/72.0.3626.121 Safari/537.36'
        }
        self.proxies = {
        }

        self.error_data_log = False

        self.output_file = open('output_{}.txt'.format(int(time.time())), 'a')

    def http_get(self, url):
        try:
            if not url.upper().startswith("HTTP://") and not url.upper().startswith("HTTPS://"):
                url = 'http://' + url
            result = self.rq.get(url=url, headers=self.headers, timeout=self.timeout, proxies=self.proxies,
                                 verify=False)
            if result.status_code == 429:
                time.sleep(self.sleep_time)
                self.http_get(url)
            return result
        except Exception as e:
            logging.error(url)
            logging.error('GET - {}'.format(e))
            exit()

    def http_post(self, url, data):
        try:
            if not url.upper().startswith("HTTP://") and not url.upper().startswith("HTTPS://"):
                url = 'http://' + url
            result = self.rq.post(url=url, data=data, headers=self.headers, timeout=self.timeout, proxies=self.proxies,
                                  verify=False)
            if result.status_code == 429:
                time.sleep(self.sleep_time)
                self.http_post(url, data)
            return result
        except Exception as e:
            logging.error('{} - {}'.format(url, data))
            logging.error('POST - {}'.format(e))
            exit()

    def login(self):
        # 先请求login获取对应的请求参数后再进行登录
        logging.info('Login: {}'.format(self.login_account))
        result = self.http_get('https://github.com/login')
        soup = BeautifulSoup(result.text, 'html.parser')
        login_data = dict()
        for input in soup.find_all('input'):
            login_data[input.get('name')] = input.get('value')
        login_data['login'] = self.login_account
        login_data['password'] = self.login_password
        self.http_post('https://github.com/session', data=login_data)
        if self.rq.cookies['logged_in'] != 'yes':
            logging.error('Github Login Failed')
            exit()

    def search_keyword(self, keyword):
        self.keyword = keyword
        now_page = 1
        logging.info('Search Keyword: {}'.format(self.keyword))
        logging.info('Get Page {} Data'.format(now_page))
        result = self.http_get(self.search_url.format(keyword=keyword, page=now_page))
        # 下载Page 1 中的文件数据
        file_url_list = self.get_file_url(result.text)
        if not file_url_list:
            logging.info('Not Found Keyword: {}'.format(self.keyword))
            return
        for file_url in file_url_list:
            self.download_file(file_url)
        # 获取总页数,同时根据配置限制最大搜索页
        soup = BeautifulSoup(result.text, 'html.parser')
        page_list = list()
        for page in soup.select('a[href*="/search?o=desc&p="]'):
            if page.get_text() not in ['Previous', 'Next']:
                page_list.append(page.get_text())
        if not page_list:
            return
        page_list.sort()
        count_page = self.search_page_max if int(page_list[-1:][0]) > self.search_page_max else int(page_list[-1:][0])
        # 下载其他Page数据
        for page in range(2, count_page + 1):
            now_page = page
            logging.info('Get Page {} Data - Max Page: {}'.format(now_page, count_page))
            result = self.http_get(self.search_url.format(keyword=keyword, page=now_page))
            for file_url in self.get_file_url(result.text):
                self.download_file(file_url)
        logging.info('Search Done')
        if self.download_flag:
            logging.info('Download File Save Path: {}/{}'.format(self.download_folder, self.keyword))

    def get_file_url(self, page_data):
        # 获取页面数据中的Code页面URL
        file_url_list = list()
        soup = BeautifulSoup(page_data, 'html.parser')
        for url in soup.select('a[data-hydro-click-hmac*=""]'):
            file_url_list.append('{}{}'.format(self.github_domain, url.get('href')))
        return file_url_list

    def download_file(self, file_url):
        # 替换RAW域名
        download_url = file_url.replace(self.github_domain, self.download_domain).replace('blob/', '')
        save_path = '{}/{}/{}'.format(self.download_folder, self.keyword,
                                      download_url.replace(self.download_domain + '/', ''))
        if self.download_flag:
            logging.info('Download File: {}'.format(file_url))
        file_data = self.http_get(download_url).text
        logging.info('Data Check: {}'.format(file_url))
        if self.data_check(file_data, file_url):
            if self.download_flag:
                # 检查对应的多级目录是否存在,不存在则创建
                if not os.path.isdir(os.path.split(save_path)[0]):
                    os.makedirs(os.path.split(save_path)[0])
                # 下载文件同时在文件开头加入文件在Github中的URL
                add_data = '{flag} Github URL {flag}\n\n{url}\n\n{flag} Github URL {flag}'.format(flag='#' * 30,
                                                                                                  url=file_url)
                with open(save_path, 'w') as f:
                    f.write('{}\n\n\n\n\n{}'.format(add_data, file_data))
                logging.info('Save File: {}'.format(save_path))
        else:
            logging.info('Data Check False')

    def data_check(self, file_data, file_url):
        # 对文件数据进行单独处理
        try:
            return_flag = False
            # 检查下载的文件中是否包含搜索的keyword
            if self.keyword in file_data:
                return_flag = True
            return return_flag
        except Exception as e:
            logging.error('Data Check - {}'.format(e))
            if self.error_data_log:
                logging.error('Error Data: {}'.format(base64.b64encode(str(file_data).encode()).decode()))
            return False


def main():
    """
    脚本主函数
    :return: 
    """
    github = GithubSearch()
    github.login()
    github.search_keyword('weinull')


if __name__ == '__main__':
    main()

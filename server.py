# !/usr/bin/env python
# -*- coding: utf-8 -*-
#
# FileName:      server.py
# Author:        binss
# Create:        2016-05-14 09:58:54
# Description:   No Description
#

import os
from tornado.ioloop import IOLoop
from tornado.options import define, options
from tornado.web import *
from tornado import gen

from log import logger
from auth import *


class BaseHandler(RequestHandler):
    # 重写
    def get_current_user(self):
        username = self.get_secure_cookie("username")
        if username:
            if isinstance(username, bytes):
                username = username.decode()
            return username
        else:
            return ""



class LoginHandler(BaseHandler):
    def get(self):
        mode = self.get_secure_cookie("kancolle_cache_mode")
        if not mode:
            mode = 1
        self.render('login.html', user=self.current_user, errmsg="", mode=1)

    async def post(self):
        username = self.get_argument('username', None)
        password = self.get_argument('password', None)
        mode = self.get_argument('mode', '1')

        logger.info("User[%s] login, mode[%s]", username, mode)
        self.set_secure_cookie("kancolle_cache_mode", mode)

        if username and password:
            kancolle = KancolleAuth(username, password)
            # mode为游戏运行方式
            if mode in ('1', '2', '3'):
                try:
                    await kancolle.get_flash()
                    self.set_secure_cookie('api_token', kancolle.api_token)
                    self.set_secure_cookie('api_starttime', str(kancolle.api_starttime))
                    self.set_secure_cookie('world_ip', kancolle.world_ip)

                    logger.info("User[%s] login success", username)
                    if mode == 2:
                        self.redirect("/kcv/")
                    elif mode == 3:
                        self.redirect("/poi/")
                    else:
                        self.redirect("/web/")

                except OOIAuthException as e:
                    logger.info("User[%s] login fail, reason: %s", username, e.message)
                    self.render("login.html", user=self.current_user, errmsg=e.message, mode=mode)

            elif mode == '4':
                try:
                    osapi_url = await kancolle.get_osapi()
                    self.set_cookie('osapi_url', osapi_url)
                    logger.info("User[%s] login success", username)
                    self.redirect("/connector/")
                except OOIAuthException as e:
                    logger.info("User[%s] login fail, reason: %s", username, e.message)
                    self.render("login.html", user=self.current_user, errmsg=e.message, mode=mode)
            else:
                logger.error("User[%s] login fail, reason: unknown mode: %d", username, mode)
                self.render("login.html", user=self.current_user, errmsg="游戏方式错误", mode=1)
        else:
            self.render("login.html", user=self.current_user, errmsg="请输入完整的账号（邮箱）和密码", mode=1)


class WebHandler(BaseHandler):
    def get(self):
        token = self.get_secure_cookie('api_token')
        starttime = self.get_secure_cookie('api_starttime')
        world_ip = self.get_secure_cookie('world_ip')
        # 缺一不可，重定向到登陆页面
        if token and starttime and world_ip:
            self.render("normal.html", user=self.current_user, scheme=self.request.protocol, host=self.request.host, token=token, starttime=starttime)
        else:
            self.clear_all_cookies()
            self.redirect('/')


CONTENT_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".swf": "application/x-shockwave-flash",
    ".mp3": "audio/mpeg"
}


class CacheHandler(BaseHandler):
    async def get(self, target):
        query = self.request.query
        ext_name = os.path.splitext(target)[1]
        file_path = "./cache/kcs/" + target

        if not os.path.exists(file_path):
            url = 'http://203.104.209.23/kcs/%s?%s' % (target, query)
            logger.debug(url)

            headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}
            request = HTTPRequest(url=url, method='GET', headers=headers, use_gzip=True, request_timeout=REQUEST_TIMEOUT)
            http_client = AsyncHTTPClient()

            try:
                response = await http_client.fetch(request)
            except HTTPError:
                self.send_error(404)

            body = response.body
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "wb") as f:
                f.write(body)

        self.set_header('Cache-Control', 'max-age=2592000, public')
        self.set_header('Content-Type', CONTENT_TYPE[ext_name])
        self.set_header('X-Accel-Redirect', file_path[1:])


class WorldImageHandler(RequestHandler):
    async def get(self, size):
        world_ip = self.get_secure_cookie('world_ip').decode()
        if world_ip:
            ip_sections = map(int, world_ip.split('.'))
            formatted_ip = '_'.join([format(x, '03') for x in ip_sections])
            filename = "%s_%s.png" % (formatted_ip, size)
            file_path = './cache/world/' + filename

            if not os.path.exists(file_path):
                url = 'http://203.104.209.23/kcs/resources/image/world/%s?%s' % (filename, self.request.query)
                logger.debug(url)

                headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}
                request = HTTPRequest(url=url, method='GET', headers=headers, use_gzip=True, request_timeout=REQUEST_TIMEOUT)
                http_client = AsyncHTTPClient()

                try:
                    response = await http_client.fetch(request)
                except HTTPError:
                    raise HTTPError(404)

                body = response.body
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "wb") as f:
                    f.write(body)

            self.set_header('Cache-Control', 'max-age=2592000, public')
            self.set_header('Content-Type', 'image/png')
            self.set_header('X-Accel-Redirect', file_path[1:])
        else:
            raise HTTPError(404)




api_start2 = None


# 镇守府图片和api_start2内容的变量
class APIHandler(BaseHandler):
    def check_xsrf_cookie(self):
        pass

    async def post(self, action):
        world_ip = self.get_secure_cookie('world_ip').decode()
        if world_ip:
            global api_start2
            if action == 'api_start2' and api_start2:
                self.set_header('Content-Type', 'text/plain')
                self.write(api_start2)
            else:
                referer = self.request.headers.get('Referer')
                referer = referer.replace(self.request.headers.get('Host'), world_ip)
                referer = referer.replace('https', 'http')
                referer = referer.replace('&world_ip=' + world_ip, '')
                url = 'http://' + world_ip + self.request.uri
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36',
                    'Origin': 'http://' + world_ip + '/',
                    'Referer': referer,
                    'X-Requested-With': 'ShockwaveFlash/18.0.0.232'
                }
                http_client = AsyncHTTPClient()
                response = await http_client.fetch(url, method='POST', headers=headers, body=self.request.body,
                                                   connect_timeout=60, request_timeout=120)
                self.set_header('Content-Type', response.headers['Content-Type'])
                self.write(response.body)
                if action == 'api_start2' and len(response.body) > 100000:
                    api_start2 = response.body
        else:
            self.send_error(403)


class LogoutHandler(BaseHandler):
    def get(self):
        self.clear_all_cookies()
        self.redirect('/')


def main():
    rel = lambda *x: os.path.abspath(os.path.join(os.path.dirname(__file__), *x))

    define('listen', metavar='IP', default='0.0.0.0', help='listen on IP address (default 0.0.0.0)')
    define('port', metavar='PORT', default=8888, type=int, help='listen on PORT (default 8888)')
    define('debug', metavar='True|False', default=True, type=bool, help='debug mode')
    define("config", default="", help="config file")


    options.parse_command_line()

    settings = dict(
        template_path=rel('templates'),
        static_path=rel('static'),
        debug=options.debug,
        xsrf_cookies=True,
        cookie_secret="bZJc2sWbQLKos6GkHn/VB9oXwQtsw2d1QRvJ5/xJ89E=",
        login_url="/",
        # ui_methods=uimodule,
    )

    if options.debug:
        import logging
        logger.setLevel(logging.DEBUG)

    application = Application([
        (r'/', LoginHandler),
        (r'/web[/]*', WebHandler),
        (r'/kcs/resources/image/world/.*(l|s|t)\.png', WorldImageHandler),
        (r'/kcs/(.*)', CacheHandler),
        (r'/kcsapi/(.*)', APIHandler),
        (r'/logout[/]*', APIHandler),


    ], **settings)

    application.listen(address=options.listen, port=options.port)


    logger.info("http server started on %s:%s" % (options.listen, options.port))

    IOLoop.instance().start()


if __name__ == '__main__':
    main()

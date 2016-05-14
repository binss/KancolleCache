import json
import re
import time
from urllib.parse import urlencode, urlparse, parse_qs

from tornado.escape import json_encode, json_decode
from tornado.httpclient import AsyncHTTPClient, HTTPRequest, HTTPError
from log import logger
from tornado import gen

REQUEST_TIMEOUT = 60


class OOIBaseException(Exception):

    def __init__(self, message):
        super().__init__(self)
        self.message = message


class OOIAuthException(OOIBaseException):
    pass


# 舰队collection 认证类
class KancolleAuth:
    # 认证过程中需要的URLs
    urls = {'login': 'https://www.dmm.com/my/-/login/',
            'ajax': 'https://www.dmm.com/my/-/login/ajax-get-token/',
            'auth': 'https://www.dmm.com/my/-/login/auth/',
            'game': 'http://www.dmm.com/netgame/social/-/gadgets/=/app_id=854854/',
            'make_request': 'http://osapi.dmm.com/gadgets/makeRequest',
            'get_world': 'http://203.104.209.7/kcsapi/api_world/get_id/%s/1/%d',
            'get_flash': 'http://%s/kcsapi/api_auth_member/dmmlogin/%s/1/%d',
            'flash': 'http://%s/kcs/mainD2.swf?api_token=%s&amp;api_starttime=%d'}

    # 各镇守府的IP列表
    world_ip_list = (
        "203.104.209.71",
        "203.104.209.87",
        "125.6.184.16",
        "125.6.187.205",
        "125.6.187.229",
        "125.6.187.253",
        "125.6.188.25",
        "203.104.248.135",
        "125.6.189.7",
        "125.6.189.39",
        "125.6.189.71",
        "125.6.189.103",
        "125.6.189.135",
        "125.6.189.167",
        "125.6.189.215",
        "125.6.189.247",
        "203.104.209.23",
        "203.104.209.39",
        "203.104.209.55",
        "203.104.209.102",
    )


    # 匹配网页中所需信息的正则表达式
    patterns = {
        'dmm_token': re.compile(r'"DMM_TOKEN", "([\d|\w]+)"'),
        'token': re.compile(r'"token": "([\d|\w]+)"'),
        'reset': re.compile(r'認証エラー'),
        'osapi': re.compile(r'URL\W+:\W+"(.*)",'),
        'sesid': re.compile(r'INT_SESID=([^;]+);')
    }


    def __init__(self, username, password):
        self.username = username
        self.password = password

        self.headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}

        self.http_client = AsyncHTTPClient()

        # 初始化登录过程中所需的变量
        self.dmm_token = None
        self.token = None
        self.idKey = None
        self.pwdKey = None
        self.owner = None
        self.osapi_url = None
        self.world_id = None
        self.world_ip = None
        self.api_token = None
        self.api_starttime = None
        self.flash = None


    def __del__(self):
        pass
        # self.session.close()


    # STEP 1 访问dmm登陆页面，获取dmm_token和token
    async def _get_dmm_tokens(self):
        request = HTTPRequest(url=self.urls['login'], method='GET', body=None, headers=self.headers,
                              follow_redirects=False, use_gzip=True, request_timeout=REQUEST_TIMEOUT)
        response = await self.http_client.fetch(request)

        html = response.body.decode()

        # 用正则从页面中匹配出dmm_token和token
        m = self.patterns['dmm_token'].search(html)
        if m:
            self.dmm_token = m.group(1)
        else:
            logger.debug("Fetch DMM token failed, reason: cannot find dmm_token in return page")
            raise OOIAuthException('获取DMM token失败')

        m = self.patterns['token'].search(html)
        if m:
            self.token = m.group(1)
        else:
            logger.debug("Fetch DMM token failed, reason: cannot find token in return page")
            raise OOIAuthException('获取token失败')

        logger.debug("Fetch DMM token success, dmm_token[%s], token[%s]", self.dmm_token, self.token)
        return self.dmm_token, self.token


    # STEP 2 模拟登陆页AJAX请求，获取idKey、pwdKey和第二个token
    async def _get_ajax_token(self):
        self.headers.update({'Origin': 'https://www.dmm.com',
                             'Referer': self.urls['login'],
                             'DMM_TOKEN': self.dmm_token,
                             'Cookie': 'ckcy=1; check_open_login=1; check_down_login=1',
                             'X-Requested-With': 'XMLHttpRequest'})
        data = {'token': self.token}

        request = HTTPRequest(url=self.urls['ajax'], method='POST', body=urlencode(data), headers=self.headers,
                              follow_redirects=False, use_gzip=True, request_timeout=REQUEST_TIMEOUT)
        response = await self.http_client.fetch(request)

        j = json_decode(response.body.decode())

        self.token = j['token']
        self.idKey = j['login_id']
        self.pwdKey = j['password']

        logger.debug("Fetch DMM ajax token success, token[%s], idKey[%s], pwdKey[%s]", self.token, self.idKey, self.pwdKey)
        return self.token, self.idKey, self.pwdKey


    # STEP 3 登陆DMM，获取osapi_url
    async def _get_osapi_url(self):
        del self.headers['DMM_TOKEN']
        del self.headers['X-Requested-With']
        # 获取user session
        data = {'login_id': self.username, 'password': self.password, 'token': self.token, self.idKey: self.username, self.pwdKey: self.password}
        request = HTTPRequest(url=self.urls['auth'], method='POST', body=urlencode(data), headers=self.headers,
                              follow_redirects=False, use_gzip=True, request_timeout=REQUEST_TIMEOUT)
        try:
            response = await self.http_client.fetch(request)
            html = response.body.decode()
            m = self.patterns['reset'].search(html)
            if m:
                logger.debug("Fetch osapi failed, reason: user should change password manually")
                raise OOIAuthException('DMM强制要求用户修改密码')
            else:
                logger.debug("Fetch osapi failed, reason: username or password error")
                raise OOIAuthException('用户名或密码错误，请重新输入')

        except HTTPError as e:
            if e.code == 302:
                response = e.response
                raw_cookie = response.headers.get('Set-Cookie')
                m = self.patterns['sesid'].search(raw_cookie)
                if m:
                    sesid = m.group(1)
                else:
                    logger.debug("Fetch osapi failed, reason: cannot get dmm user session")
                    raise OOIAuthException('DMM用户session获取失败')
            else:
                logger.debug("Fetch osapi failed, reason: http error, code[%d]", e.code)
                raise OOIAuthException('网络故障')

        # 通过session登陆游戏，获取osapi
        self.headers.update({'Cookie': 'ckcy=1; check_open_login=1; check_down_login=1; INT_SESID=' + sesid,
                             'Referer': self.urls['auth']})

        request = HTTPRequest(url=self.urls['game'], method='GET', body=None, headers=self.headers,
                              follow_redirects=False, use_gzip=True, request_timeout=REQUEST_TIMEOUT)
        response = await self.http_client.fetch(request)

        html = response.body.decode()
        m = self.patterns['osapi'].search(html)
        if m:
            self.osapi_url = m.group(1)
        else:
            logger.debug("Fetch osapi failed, reason: username or password error")
            raise OOIAuthException('用户名或密码错误，请重新输入')

        logger.debug("Fetch osapi success, osapi[%s]", self.osapi_url)

        return self.osapi_url



    # STEP 4 访问osapi_url，获取用户所在服务器的ID和IP地址
    async def _get_world(self):
        qs = parse_qs(urlparse(self.osapi_url).query)
        self.owner = qs['owner'][0]
        self.st = qs['st'][0]
        # 构造游戏服务器的url
        url = self.urls['get_world'] % (self.owner, int(time.time() * 1000))
        self.headers['Referer'] = self.osapi_url

        request = HTTPRequest(url=url, method='GET', headers=self.headers,
                              follow_redirects=False, use_gzip=True, request_timeout=REQUEST_TIMEOUT)
        response = await self.http_client.fetch(request)

        html = response.body.decode()
        svdata = json.loads(html[7:])
        if svdata['api_result'] == 1:
            self.world_id = svdata['api_data']['api_world_id']
            self.world_ip = self.world_ip_list[self.world_id - 1]
        else:
            logger.debug("Fetch game server info failed, reason: game server return incorrect result")
            raise OOIAuthException('查找所在的镇守府出错')

        logger.debug("Fetch game server info success, world_id[%s], world_ip[%s]", self.world_id, self.world_ip)
        return self.world_id, self.world_ip, self.st


    # STEP 5 根据服务器IP和用户ID，从DMM处获得用户的api_token、api_starttime，并生成游戏FLASH的地址
    async def _get_api_token(self):
        url = self.urls['get_flash'] % (self.world_ip, self.owner, int(time.time() * 1000))
        data = {'url': url,
                'httpMethod': 'GET',
                'authz': 'signed',
                'st': self.st,
                'contentType': 'JSON',
                'numEntries': '3',
                'getSummaries': 'false',
                'signOwner': 'true',
                'signViewer': 'true',
                'gadget': 'http://203.104.209.7/gadget.xml',
                'container': 'dmm'}


        request = HTTPRequest(url=self.urls['make_request'], method='POST', body=urlencode(data), headers=self.headers,
                              follow_redirects=False, use_gzip=True, request_timeout=REQUEST_TIMEOUT)
        try:
            response = await self.http_client.fetch(request)
        except HTTPError as e:
            if e.code == 599:
                raise OOIAuthException('登陆超时')

        html = response.body.decode()
        svdata = json.loads(html[27:])
        if svdata[url]['rc'] != 200:
            logger.debug("Fetch game info failed, reason: game server reject")
            raise OOIAuthException('通信故障，进入镇守府失败')
        svdata = json.loads(svdata[url]['body'][7:])
        if svdata['api_result'] != 1:
            logger.debug("Fetch game info failed, reason: game server return incorrect result")
            raise OOIAuthException('进入镇守府失败')

        self.api_token = svdata['api_token']
        self.api_starttime = svdata['api_starttime']
        self.flash = self.urls['flash'] % (self.world_ip, self.api_token, self.api_starttime)

        logger.debug("Fetch game info success, api_token[%s], api_starttime[%s]", self.api_token, self.api_starttime)
        return self.api_token, self.api_starttime, self.flash

    # 提取游戏的osapi_url
    async def get_osapi(self):
        await self._get_dmm_tokens()
        await self._get_ajax_token()
        await self._get_osapi_url()
        return self.osapi_url

    # 登陆游戏，获取游戏FLASH地址
    async def get_flash(self):
        await self.get_osapi()
        await self._get_world()
        await self._get_api_token()
        return self.flash

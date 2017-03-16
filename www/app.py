#coding=utf-8
#!/usr/bin/env python
import logging; logging.basicConfig(level=logging.INFO)

import asyncio, os, json, time
from datetime import datetime

from aiohttp import web
import orm
from jinja2 import Environment, FileSystemLoader
from coroweb import add_routes, add_static


def index(request):
    return web.Response(body=b'<h1>Awesome</h1>')


def init_jinja2(app, **kw):
    logging.info('init jinja2...')
    options = dict(
        autoescape = kw.get('autoescape', True),
        block_start_string = kw.get('block_start_string', '{%'),
        block_end_string = kw.get('block_end_string', '%}'),
        variable_start_string = kw.get('variable_start_string', '{{'),
        variable_end_string = kw.get('variable_end_string', '}}'),
        auto_reload = kw.get('auto_reload', True)
    )
    path = kw.get('path', None)
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    logging.info('set jinja2 template path: %s' % path)
    env = Environment(loader=FileSystemLoader(path), **options)
    filters = kw.get('filters', None)
    if filters is not None:
        for name, f in filters.items():
            env.filters[name] = f
    app['__templating__'] = env




# middleware拦截器

#拦截器在处理URL之前将cookie解析出来，并将登录用户绑定到request对象上，这样后续的URL处理函数可以通过request来拿到登录用户
@asyncio.coroutine
def auth_factory(app, handler):
    @asyncio.coroutine
    def auth(request):
        logging.info('check user: %s %s' % (request.method, request.path))
        request.__user__ = None
        cookie_str = request.cookies.get(COOKIE_NAME)
        if cookie_str:
            user = yield from cookie2user(cookie_str)
            if user:
                logging.info('set current user: %s' % user.email)
                request.__user__ = user
        return (yield from handler(request))
    return auth



@asyncio.coroutine
def logger_factory(app, handler):
    @asyncio.coroutine
    def logger(request):
        # 记录日志:
        logging.info('Request: %s %s' % (request.method, request.path))
        # 继续处理请求:
        return (yield from handler(request))
    return logger

@asyncio.coroutine
def data_factory(app, handler):
    def parse_data(request):
        if request.method == 'POST':
            if request.content_type.startswith('application/json'):
                request.__data__ = yield from request.json()
                logging.info('request json: %s' % str(request.__data__))
            elif request.content_type.startswith('application/x-www-form-urlencoded'):
                request.__data__ = yield from request.post()
                logging.info('request form: %s' % str(request.__data__))
        return (yield from handler(request))
    return parse_data



@asyncio.coroutine
def response_factory(app, handler):
    @asyncio.coroutine
    def response(request):
        logging.info('Response handler...')
        # 结果:
        r = yield from handler(request)
        # StreamResponse是aiohttp定义response的基类
        if isinstance(r, web.StreamResponse):
            return r
        # 字节流
        if isinstance(r, bytes):
            resp = web.Response(body=r)
            resp.content_type = 'application/octet-stream'
            return resp
        # 字符串
        if isinstance(r, str):
            # 判断响应结果是否为重定向，是就返回重定向后的结果
            if r.startswith('redirect:'):
                return web.HTTPFound(r[9:])  # 过滤"redirect:"
            #utf8编码
            resp = web.Response(body=r.encode('utf-8'))
            resp.content_type = 'text/html;charset=utf-8'
            return resp
        # 读取jinja2模板信息
        if isinstance(r, dict):
            template = r.get('__template__')
            
            if template is None:
                resp = web.Response(body=json.dumps(r, ensure_ascii=False, default=lambda o: o.__dict__).encode('utf-8'))
                resp.content_type = 'application/json;charset=utf-8'
                return resp
            else:
                #r["__user__"] = request.__user__  # 增加__user__,前端页面将依次来决定是否显示评论框
                resp = web.Response(body=app['__templating__'].get_template(template).render(**r).encode('utf-8'))
                resp.content_type = 'text/html;charset=utf-8'
                return resp
        
        # 状态码
        if isinstance(r, int) and r >= 100 and r < 600:
            return web.Response(r)
        
        if isinstance(r, tuple) and len(r) == 2:
            t, m = r #t为http状态码，m为错误描述，返回状态码和错误描述
            if isinstance(t, int) and t >= 100 and t < 600:
                return web.Response(t, str(m))  
            
        #默认以字符串形式返回响应结果，设置类型为普通文本    
        resp = web.Response(body=str(r).encode('utf-8'))
        resp.content_type = 'text/plain;charset=utf-8'
        return resp
    
    return response
# 时间过滤器
def datetime_filter(t):
    delta = int(time.time() - t)
    if delta < 60:
        return '1分钟前'
    if delta < 3600:
        return '%s分钟前' % (delta // 60)
    if delta < 86400:
        return '%s小时前' % (delta // 3600)
    if delta < 604800:
        return '%s天前' % (delta // 86400)
    dt = datetime.fromtimestamp(t)
    return '%s年%s月%s日' % (dt.year, dt.month, dt.day)





@asyncio.coroutine
def init(loop):
    yield from orm.create_pool(loop=loop, host='127.0.0.1', port=3306, user='root', password='220016', db='awesome')
    
    app = web.Application(loop=loop, middlewares=[
        logger_factory, response_factory
    ])
    
    # 初始化jinja2模板
    init_jinja2(app, filters=dict(datetime=datetime_filter))
    add_routes(app, 'handlers') 
    add_static(app)
    srv = yield from loop.create_server(app.make_handler(), '127.0.0.1', 8888)
    logging.info('server started at http://127.0.0.1:8888...')
    return srv


loop = asyncio.get_event_loop()
loop.run_until_complete(init(loop))
loop.run_forever()
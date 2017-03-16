#!/usr/bin/env python3
#coding=utf-8
from bs4 import __author__
import functools
#2017.03.16
__author__ = 'Qinv'

import asyncio, os, inspect, logging
from urllib import parse
from aiohttp import web
from apis import APIError

def get(path):
    '''
    Define decorator @get('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'GET'
        wrapper.__route__ = path
        return wrapper
    return decorator

def post(path):
    '''
    Define decorator @post('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args,**kw):
            return func(*args,**kw)
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper
    return decorator


#inspect模板的应用
#(1)对是否是模块，框架，函数等进行类型检查。
#(2)获取源码
#(3)获取类或函数的参数的信息
#(4)解析堆栈
#这里用到(3)，即用于获取类或函数的参数的信息

# 返回函数func中没有默认值的关键词参数的元组
def get_required_kw_args(func):
    args = []
    params = inspect.signature(func).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)


# 返回函数func中关键词参数的元组
def get_named_kw_args(func):
    args = []
    params = inspect.signature(func).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)


# 判断函数func有没有关键词参数，有就返回True
def has_named_kw_args(func):
    params = inspect.signature(func).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True

# 判断函数func有没有可变的关键词参数(**kw)，有就返回True
def has_var_kw_arg(func):
    params = inspect.signature(func).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True


#判断函数func的参数中有没有参数名为request的参数
def has_request_arg(func):
    sig = inspect.signature(func)
    params = sig.parameters
    found = False  
    for name, param in params.items():
        if name == 'request':
            found = True
            continue  
        # request参数必须是最后一个位置和关键词参数
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError('request parameter must be the last named parameter in function: %s%s' % (func.__name__, str(sig)))
    return found



#定义RequestHandler()封装一个URL处理函数
#RequestHandler是一个类，但定义了__call__()方法，因此是一个callable对象
#RequestHandler目的就是从URL函数中分析其需要接收的参数，从request中获取必要的参数
#调用URL函数，然后把结果转换为web.Response对象，这样，就完全符合aiohttp框架的要求
class RequestHandler(object):

    def __init__(self, app, func):
        self._app = app
        self._func = func
        self._has_request_arg = has_request_arg(func)
        self._has_var_kw_arg = has_var_kw_arg(func)
        self._has_named_kw_args = has_named_kw_args(func)
        self._named_kw_args = get_named_kw_args(func)
        self._required_kw_args = get_required_kw_args(func)

    @asyncio.coroutine
    def __call__(self, request):
        kw = None  # 假设不存在关键字参数
        # 如果func的参数有可变的关键字参数或关键字参数
        if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:
            if request.method == 'POST':
                # content_type是request提交的消息主体类型，没有就返回丢失消息主体类型
                if not request.content_type:
                    return web.HTTPBadRequest('Missing Content-Type.')
                ct = request.content_type.lower()
                
                if ct.startswith('application/json'): #消息主体是序列化后的json字符串
                    params = yield from request.json()
                    if not isinstance(params, dict): #如果json中信息不是dict类型表示JSON出错
                        return web.HTTPBadRequest('JSON body must be object.')
                    kw = params
                #消息主体是提交的表单    
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    # request.post方法从request body读取POST参数,即表单信息,并包装成字典赋给kw变量
                    params = yield from request.post()
                    kw = dict(**params)
                else: #消息主体是不支持的类型
                    return web.HTTPBadRequest('Unsupported Content-Type: %s' % request.content_type)
            
            
            if request.method == 'GET':
                qs = request.query_string #url中的查询字串
                if qs:
                    kw = dict()
                    for k, v in parse.parse_qs(qs, True).items():
                        kw[k] = v[0]
        
        # 如果经过以上处理 kw是None，则获取请求的abstract math info
        # match_info主要是保存像@get('/blog/{id}')里面的id，就是路由路径里的参数
        if kw is None:
            kw = dict(**request.match_info)
        else:
            # 如果经过以上处理了，kw不为空了，而且没有可变的关键字参数，但是有关键字参数
            if not self._has_var_kw_arg and self._named_kw_args:
                # remove all unamed kw:删除不是func关键字的项
                copy = dict()
                for name in self._named_kw_args:
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            # check named arg:
             # 遍历request.match_info,再把abstract math info的值加入kw中
            for k, v in request.match_info.items():
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s' % k)
                kw[k] = v
                
        # 如果func的参数有request，则再给kw加上request的key和值
        if self._has_request_arg:
            kw['request'] = request
       
        # check required kw:
        # 如果func的参数中有无默认值的关键字参数
        if self._required_kw_args:
            for name in self._required_kw_args: #因为kw中必须包括func中所有的无默认值的关键字参数
                if not name in kw:
                    return web.HTTPBadRequest('Missing argument: %s' % name)
        
        
        
        logging.info('call with args: %s' % str(kw))
        try:
            print(self._func.__name__) 
            r = yield from self._func(**kw)
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)

# 向app中添加静态文件目录
def add_static(app):
    # os.path.abspath(__file__), 返回当前脚本的绝对路径(包括文件名)
    # os.path.dirname(), 去掉文件名,返回目录路径
    # os.path.join(), 将分离的各部分组合成一个路径名
    # 将本文件同目录下的static目录(即www/static/)加入到应用的路由管理器中
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/', path))

# 注册一个URL处理函数
def add_route(app, func):
    method = getattr(func, '__method__', None)  # 获取func.__method__属性,若不存在将返回None
    path = getattr(func, '__route__', None)  # 获取func.__route__属性,若不存在将返回None
    if path is None or method is None:  # 如果两个属性其中之一没有值，那就会报错
        raise ValueError('@get or @post not defined in %s.' % str(func))
    
    # 如果函数func是不是一个协程或者generator，就把这个函数设置为协程
    if not asyncio.iscoroutinefunction(func) and not inspect.isgeneratorfunction(func):
        func = asyncio.coroutine(func)
    logging.info('add route %s %s => %s(%s)' % (method, path, func.__name__, ', '.join(inspect.signature(func).parameters.keys())))
    app.router.add_route(method, path, RequestHandler(app, func))  # 注册request handler


# 将handlers模块中所有请求处理函数提取出来交给add_route自动去处理
def add_routes(app, module_name):
    
    n = module_name.rfind('.')#传入的module_name为handlers
    if n == (-1):
        mod = __import__(module_name, globals(), locals())
    else:#传入的module_name为handlers.handlers
        name = module_name[n+1:]
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
    for attr in dir(mod):
        # 排除以"__"开头的属性，即私有属性
        if attr.startswith('_'):
            continue
        func = getattr(mod, attr)
        #检查提取的func是否为callable对象
        if callable(func):
            method = getattr(func, '__method__', None)
            path = getattr(func, '__route__', None)
            # 如果存在__method__和__route__方法，则满足注册条件，是URL处理函数，添加到app中注册
            if method and path:
                add_route(app, func)



#!/usr/bin/env python3
#coding=utf-8
from bs4 import __author__
#2017.03.02
__author__ = 'Qinv'
import sys 
import logging; 
logging.basicConfig(level=logging.INFO)
import asyncio, os, json, time
import aiomysql


def log(sql,args=()):  
    logging.info('SQL:%s' %sql)  

@asyncio.coroutine
def create_pool(loop,**kw):
    logging.info('create database connection pool...') 
    global __pool
    __pool = yield from aiomysql.create_pool(
       host=kw.get('host','localhost'),
       port=kw.get('port',3306),
       user=kw['user'],
       password=kw['password'],
       db=kw['db'],
       charset=kw.get('charset','utf8'),
       autocommit=kw.get('autocommit',True),
       maxsize=kw.get('maxsize',10),
       minsize=kw.get('minsize',1),
       loop=loop
       )
    
@asyncio.coroutine
def destroy_pool():
    global __pool
    if __pool is not None:
        __pool.close() #关闭进程池,close不是协程
        yield from __pool.wait_closed() #wait_close()是一个协程
        
@asyncio.coroutine
def select(sql,args,size=None):
    log(sql,args)
    global __pool
    with (yield from __pool) as conn:
        cur = yield from conn.cursor(aiomysql.DictCursor)
        yield from cur.execute(sql.replace('?','%s'),args or ())
        if size:
            rs = yield from cur.fetchmany(size) #返回查询结果(条数为size),返回一个list
        else:
            rs = yield from cur.fetchall() #返回所有查询结果
        yield from cur.close() #关闭游标
        logging.info('rows returned: %s' %len(rs))
        return rs

# 封装INSERT, UPDATE, DELETE  
@asyncio.coroutine
def execute(sql,args, autocommit=True):
    log(sql,args)
    global __pool
    with (yield from __pool) as conn:
        try:
            cur = yield from conn.cursor()
            yield from cur.execute(sql.replace('?', '%s'), args)
            yield from conn.commit()
            affect_lines = cur.rowcount
            yield from cur.close()
        except BaseException as e:
            raise
        return affect_lines
    


#用于把查询字段计数替换成sql识别的?
def create_args_string(num):  
    lol=[]  
    for n in range(num):  
        lol.append('?')  
    return (','.join(lol)) 


class Field(object):
    def __init__(self,name,column_type,primary_key,default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default
        
    def __str__(self):
        return '<%s, %s, %s>' % (self.__class__.__name__,self.name,self.column_type)

class StringField(Field):
    def __init__(self,name=None,primary_key=False,default=None,ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)

# 布尔类型不可以作为主键  
class BooleanField(Field):  
    def __init__(self, name=None,primary_key=False, default=False,ddl='Boolean'):  
        super().__init__(name,ddl,primary_key, default) 

class IntegerField(Field):  
    def __init__(self, name=None, primary_key=False, default=0,ddl='int'):  
        super().__init__(name, ddl, primary_key, default) 

class FloatField(Field):
    def __init__(self, name=None, primary_key=False, default=0.0,ddl='float'):  
        super().__init__(name, ddl, primary_key, default) 

class TextField(Field):
    def __init__(self, name=None, primary_key=False, default=None,ddl='text'):  
        super().__init__(name, ddl, primary_key, default)


#model元类
class ModelMetaclass(type):
    def __new__(cls,name,bases,attrs):
        if name == 'Model': #排除对Model类的修改
            return type.__new__(cls,name,bases,attrs)
        table_name = attrs.get('__table__',None) or name
        logging.info('found table: %s (table: %s) ' %(name,table_name ))
        
        mappings = dict() # 获取Field所有主键名和Field 
        fields=[] #field保存除主键外的属性名
        primary_key = None
        
        for k,v in attrs.items():
            if isinstance(v, Field):
                logging.info('Found mapping %s===>%s' %(k, v))
                mappings[k] = v
                if v.primary_key:
                    logging.info('found primary key %s'%k)  
                    if primary_key:  
                        raise RuntimeError('Duplicated key for field') #主键不可重复
                    primary_key = k
                else:
                    fields.append(k)
        
        if not primary_key:
            raise RuntimeError('Primary key not found!') #找不到主键
        
        for k in mappings.keys():
            attrs.pop(k) #从类属性中删除Field,防止实例属性遮住类的同名属性
        
        other_fields = list(map(lambda f:'`%s`' %f, fields)) # 将除主键外的其他属性变成`id`, `name`这种形式
        # 保存属性和列的映射关系
        attrs['__mappings__'] = mappings
        attrs['__table__'] = table_name
        attrs['__primary_key__'] = primary_key
        attrs['__fields__']=fields 
        attrs['__select__']='select `%s`, %s from `%s` '%(primary_key,', '.join(other_fields), table_name)
        attrs['__insert__'] = 'insert into  `%s` (%s, `%s`) values (%s) ' %(table_name, ', '.join(other_fields), primary_key, create_args_string(len(other_fields)+1))
        attrs['__update__']='update `%s` set %s where `%s` = ?' % (table_name, ', '.join(map(lambda f:'`%s`=?' % (mappings.get(f).name or f), fields)), primary_key)  
        attrs['__delete__']='delete from `%s` where `%s`=?' %(table_name, primary_key)  
        return type.__new__(cls, name, bases, attrs)
    

#基本定义的映射的基类Model
class Model(dict,metaclass=ModelMetaclass):
    def __init__(self,**kw):
        super(Model,self).__init__(**kw)
    
    def __getattr__(self,key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError("object have no attribution: %s"% key) 
    
    def __setattr__(self,key,value):
        try:
            self[key] = value
        except KeyError:
            raise AttributeError("object have no attribution: %s"% key) 
    
    def getValue(self,key):
        return getattr(self,key,None)
    
    def getValueOrDefault(self,key):  
        value=getattr(self, key , None)  
        if value is None:  
            field = self.__mappings__[key]  
            if field.default is not None:  
                value = field.default() if callable(field.default) else field.default  
                logging.info('using default value for %s : %s ' % (key, str(value)))  
                setattr(self, key, value)  
   
        return value
    
    
    @classmethod
    @asyncio.coroutine
    #通过主键查找
    def find(cls, pk):
        rs = yield from select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])    
    
    @classmethod  
    @asyncio.coroutine
    def findAll(cls, where=None, args=None, **kw):  
        sql = [cls.__select__]  
        if where:  
            sql.append('where')  
            sql.append(where)  
        if args is None:  
            args = []  
   
        orderBy = kw.get('orderBy', None)  
        if orderBy:  
            sql.append('order by')  
            sql.append(orderBy)  
          
        limit = kw.get('limit', None)  
        if limit is not None:  
            sql.append('limit')  
            if isinstance(limit, int):  
                sql.append('?')  
                args.append(limit)  
            elif isinstance(limit, tuple) and len(limit) ==2:  
                sql.append('?,?')  
                args.extend(limit)  
            else:  
                raise ValueError('Invalid limit value : %s ' % str(limit))  
   
        rs = yield from select(' '.join(sql),args) #返回的rs是一个元素是tuple的list  
        return [cls(**r) for r in rs]  # **r 是关键字参数，构成了一个cls类的列表，就是每一条记录对应的类实例    

    @classmethod  
    @asyncio.coroutine  
    def findNumber(cls, selectField, where=None, args=None):  
        '''''find number by select and where.'''  
        sql = ['select %s __num__ from `%s`' %(selectField, cls.__table__)]  
        if where:  
            sql.append('where')  
            sql.append(where)  
        rs = yield from select(' '.join(sql), args, 1)  
        if len(rs) == 0:  
            return None  
        return rs[0]['__num__']
    
    @asyncio.coroutine
    def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        #print('save:%s' % args)
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = yield from execute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)

    @asyncio.coroutine
    def delete(self):  
        args = [self.getValue(self.__primary_key__)]  
        rows = yield from execute(self.__delete__, args)  
        if rows != 1:  
            logging.warning('failed to delete by primary key: affected rows: %s' %rows)
    
    @asyncio.coroutine       
    def update(self): #修改数据库中已经存入的数据  
        args = list(map(self.getValue, self.__fields__))   
        args.append(self.getValue(self.__primary_key__))  
        rows = yield from execute(self.__update__, args)  
        if rows != 1:  
            logging.warning('failed to update record: affected rows: %s'%rows)
            
            
            
if __name__=="__main__":#一个类自带前后都有双下划线的方法，在子类继承该类的时候，这些方法会自动调用，比如__init__  
    class User(Model): #虽然User类乍看没有参数传入，但实际上，User类继承Model类，Model类又继承dict类，所以User类的实例可以传入关键字参数  
        __table__ = 'user123'
        id = IntegerField('id',primary_key=True) #主键为id， tablename为User，即类名  
        name = StringField('name')  
        email = StringField('email')  
        password = StringField('password')  
    #创建异步事件的句柄  
    loop = asyncio.get_event_loop()  
   
    #创建实例  
    @asyncio.coroutine  
    def test():  
        yield from create_pool(loop=loop, host='localhost', port=3306, user='root', password='220016', db='awesome')  
        user = User(id=4, name='Qinv', email='595930255@qq.com', password='qinwei')  
        #r = yield from User2.findAll()  
        #print(r)  
        yield from user.save()  
        #yield from user.update()  
        #yield from user.delete()  
        #r = yield from User2.find(8)  
        #print(r)  
        #r = yield from User2.findAll()  
        #print(1, r)  
        #r = yield from User2.findAll(name='sly')  
        #print(2, r)  
        yield from destroy_pool()  #关闭pool  
   
    loop.run_until_complete(test())  
    loop.close()  
    if loop.is_closed():  
        sys.exit(0)  
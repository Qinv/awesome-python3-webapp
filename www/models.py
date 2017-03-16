import time, uuid
import orm
from orm import Model, StringField, BooleanField, FloatField, TextField
import asyncio, os, json, time
import aiomysql

#根据当前时间来生成id
def next_id():
    return '%015d%s000' % (int(time.time() * 1000), uuid.uuid4().hex)

class User(Model):
    __table__ = 'users'

    id = StringField(primary_key=True, default=next_id, ddl='varchar(50)')
    email = StringField(ddl='varchar(50)')
    passwd = StringField(ddl='varchar(50)')
    admin = BooleanField()
    name = StringField(ddl='varchar(50)')
    image = StringField(ddl='varchar(500)')
    created_at = FloatField(default=time.time)

class Blog(Model):
    __table__ = 'blogs'

    id = StringField(primary_key=True, default=next_id, ddl='varchar(50)')
    user_id = StringField(ddl='varchar(50)')
    user_name = StringField(ddl='varchar(50)')
    user_image = StringField(ddl='varchar(500)')
    name = StringField(ddl='varchar(50)')
    summary = StringField(ddl='varchar(200)')
    content = TextField()
    created_at = FloatField(default=time.time)

class Comment(Model):
    __table__ = 'comments'

    id = StringField(primary_key=True, default=next_id, ddl='varchar(50)')
    blog_id = StringField(ddl='varchar(50)')
    user_id = StringField(ddl='varchar(50)')
    user_name = StringField(ddl='varchar(50)')
    user_image = StringField(ddl='varchar(500)')
    content = TextField()
    created_at = FloatField(default=time.time)


#测试代码
#一处异步，处处异步    
@asyncio.coroutine   
def test():
    yield from orm.create_pool(loop=loop, host='localhost', port=3306, user='root', password='220016', db='awesome')
    print('!!!!!!zheli????/')
    u = User(name='xiaoming', email='12345@example.com', passwd='1234', image='image')
    yield from u.save()
    yield from orm.destroy_pool()

loop = asyncio.get_event_loop()

loop.run_until_complete(test())

loop.close()


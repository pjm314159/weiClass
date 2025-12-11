# 微助教签到
基于python实现
***
+ 仅实现二维码签到（我们老师只用二维码）
+ 两种实现web和gui
***
由于微信的机制，openid需要手动获取，<font color="red">时效两小时，
重新打开微助教会刷新openid</font><br>
且同样由于微信的机制，签到url也是只能在微信打开。<br>
所以作者本人设计了一个web，建议在微信内置的浏览器中打开
，这样就能自动跳转签到了，但你不能长期闲置页面，不然跳转不了。<br>
还有一种是gui形式，显示二维码而不跳转
***
### 项目启动
web启动于web.py<br>
gui启动于run.py<br>
openid配置于config.ini
***
### openid 配置教程
openid是微信用于识别用户的，微助教用浏览器打开，复制网址里的openid就可以了

***
### 另写了版本,用户友好型

[用户友好型wei-class](https://github.com/pjm314159/wei-class?tab=readme-ov-file)

# 校园网 / 局域网部署

这组 PowerShell 脚本用于把平台部署在一台 Windows 主机上，供同一可信局域网内的审核人员访问。后端以内置前端的 Spring Boot JAR 运行，MySQL 可以位于本机、虚拟机或局域网数据库服务器。

## 1. 本机配置

在本目录创建 `campus.local.env`。该文件包含密码和机器路径，已被 Git 忽略，不应提交：

```dotenv
LABEL_REVIEW_DB_URL=jdbc:mysql://<db-host>:3306/label_review?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai
LABEL_REVIEW_DB_USER=label_review
LABEL_REVIEW_DB_PASSWORD=<strong-password>
LABEL_REVIEW_JWT_SECRET=<base64-random-secret>
LABEL_REVIEW_BOOTSTRAP_ADMIN=true
LABEL_REVIEW_ADMIN_USER=admin
LABEL_REVIEW_ADMIN_PASSWORD=<strong-admin-password>
LABEL_REVIEW_ADMIN_DISPLAY_NAME=Platform Admin
LABEL_REVIEW_LEASE_MINUTES=10
LABEL_REVIEW_DB_HOST=<db-host>
LABEL_REVIEW_DB_PORT=3306
LABEL_REVIEW_JAVA=C:\path\to\java.exe
LABEL_REVIEW_PUBLIC_URL=http://<host-lan-ip>:8088
```

如果 MySQL 位于 VMware 虚拟机，还可以配置 `LABEL_REVIEW_VM_RUN` 和 `LABEL_REVIEW_VM_VMX`。启动脚本发现数据库不可达时会无界面启动该虚拟机，并等待数据库就绪。

## 2. 构建包含前端的 JAR

```powershell
cd platform\frontend
npm ci
npm run build

cd ..\backend
mvn -Pstandalone clean package
```

`standalone` profile 会把 `frontend/dist` 放入 Spring Boot 静态资源目录，最终只需要启动一个 JAR，不需要在审核主机上额外运行 Vite 或 Nginx。

## 3. 启动与停止

```powershell
platform\campus-deploy\start-platform.ps1
platform\campus-deploy\status-platform.ps1
platform\campus-deploy\stop-platform.ps1
```

启动脚本会检查数据库、必要时启动虚拟机、启动平台、轮询健康检查，并输出 `LABEL_REVIEW_PUBLIC_URL`。平台日志和 PID 均位于本目录的 Git 忽略文件中。

## 4. 防火墙

以管理员身份运行，默认仅允许 Windows 判断出的本地子网访问 TCP 8088：

```powershell
platform\campus-deploy\configure-firewall.ps1
```

也可以显式限制为实际校园网网段：

```powershell
platform\campus-deploy\configure-firewall.ps1 -RemoteAddress "<campus-subnet/cidr>"
```

不要为了省事把数据库端口或审核平台直接暴露到公网。跨网络协作应增加 TLS 反向代理、VPN 或零信任接入。

## 5. 多人使用

1. 管理员创建独立 `REVIEWER` 账号并分配项目。
2. 每位同事使用自己的账号登录，禁止多人共享管理员账号。
3. `claim-next` 通过数据库行锁原子领取任务，租约心跳避免永久占用。
4. 决策会记录审核人、时间、动作、版本和审计事件，可追溯到个人。
5. 主机休眠、关机或离开局域网后，其他电脑将无法访问。

本方案已用两个独立账号进行同时领取和审核验证；这证明基础并发分配流程可用，但不等同于大规模并发压测结论。

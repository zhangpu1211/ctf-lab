# 离线OCI、终端窄路由与保守网络对账（2026-10-25）

承接状态第86节；继续剩余开发，保留全部既有改动。新增实现为D01、S04/C03及D03的开发切片，全部43项判据不变，实机总验收尚未启动。[验证记录](verification-oci-routing-2026-10-25.md)区分代码/夹具与真实来宾。本轮没有在宿主执行Docker、安装来宾代理、连接真实SSH或操作用户VM。

## 受限OCI校验与转换

`ctflab_oci.py`只读取明确选择的OCI布局tar，校验整包SHA-256、单一manifest摘要、配置和各blob的大小/摘要、Linux平台及解压后层DiffID。manifest摘要、配置ImageID、压缩层摘要与未压缩DiffID分开保存，不能相互替代。

当前支持范围有意严格：单Linux amd64/arm64镜像、SHA-256、普通USTAR外包装/层tar、未压缩或gzip层；拒绝多manifest索引、外部URL/非分发层、zstd、PAX/GNU扩展、未知blob、重复路径、链接逃逸/路径穿越及畸形tar。允许层内部的普通目录/文件、受限硬链接和指向镜像根内的符号链接，但从不在宿主解包。拒绝设备节点/FIFO等特殊层条目。不是所有OCI镜像都支持，不把不支持的格式改成“已验证”。

外包装上限8GiB、累计展开16GiB、JSON每项4MiB、最多128层、每层最多10万条目，流式校验/哈希，不根据PAX长度分配任意内存。转换只写新目录并检查空间，产生无RepoTags的Docker载荷，保留原件和失败输出；不启动容器、不拉取、不传入原镜像任意标签。

依据：[OCI布局v1.1.1](https://github.com/opencontainers/image-spec/blob/v1.1.1/image-layout.md)、[OCI配置/DiffID定义v1.1.1](https://github.com/opencontainers/image-spec/blob/v1.1.1/config.md)。转换结构对照[Moby v28读取载荷实现](https://github.com/moby/moby/blob/v28.0.0/image/tarexport/load.go)；[Docker load文档](https://docs.docker.com/reference/cli/docker/image/load/)只说明装载行为，不替代本项目固定来宾/运行时验收。

```text
python3 -B tools/ctflab_oci.py inspect --input <明确选择的OCI.tar> --archive-sha256 <整包摘要> --manifest-sha256 <OCI镜像摘要> --architecture amd64
python3 -B tools/ctflab_oci.py convert --input <OCI.tar> --archive-sha256 <整包摘要> --manifest-sha256 <OCI镜像摘要> --architecture amd64 --destination <新的输出目录>
```

这些静态命令可以在宿主使用，不会调用Docker。合法来源、许可和信任仍由宿主内容/课程管理负责，单独提供摘要不等于来源可信。

## 接入专用来宾的容器准备

既有agents节点可选 `images` 映射：键为已声明容器的 `repo@sha256:<manifest摘要>`，值为整OCI包摘要。没有images字段时保持原编译字段/摘要和预载RepoDigests路径；未使用的映射、显式null或错误摘要拒绝。声明变更仍受完整profile/实例/代次绑定约束，不能在线改旧运行配置。

专用来宾固定位置为 `/var/lib/ctflab-guest/oci/<整包SHA-256>`，必须是独立私有普通文件。**本轮没有把镜像自动送入来宾**；来源合法、仅在新专用测试VM中明确暂存的材料仍是前置条件，不能把宿主远程上传成功当成来宾已取得文件。

显式 `containers-prepare` 先验证现有网络、所有包/资源/声明，再按持久意图转换、调用该专用来宾固定Docker Unix socket执行 `image load --quiet --input`，复核ImageID、Linux架构和RootFS层列表，保存与策略绑定的原OCI引用→配置ImageID证明。之后只按精确ImageID、`--pull=never`、非root/只读/无capabilities及现有配额创建容器，不启动。后续启动/停止会重验映像身份；镜像变化拒绝。

每步先记录意图；装载中断不重放、不强杀或删除。OCI载荷、转换输出、日志和旧卷保留。Docker daemon中断/半装载的完整修复仍未实现，不能借网络对账入口结清容器操作。原生Docker、实际OCI样本/服务及卷重置未验，D01/D03未整项通过。新安装材料增加OCI/路由模块与空oci目录，只生成材料，不安装到用户已有VM。

Docker CLI超时不证明daemon没有继续装载：代理保留该效果为unknown，并继续提供只读步骤查询；不会因超时自动再次load、重启daemon或结束VM。超时路径由固定工具调用的异常转换和代理消息流共同验证，不把脚本替身当作真实daemon取消证明。

长操作丢失回应后，重连的configure握手可在原总时限内排空最多8条同实例/代次/策略、合法UUID的迟到回复，仅接受当前握手ID；外国绑定立即拒绝。普通及修改操作仍严格拒绝错配ID，不排空或重发。该处理不证明真实virtio/来宾长操作已验；过多旧回复仍拒绝并保留现场。

## 单网卡终端的窄路由

agents节点可选 `endpoint`，包含routes和flows，初版只支持单网卡终端，不能同时声明路由器forward flows或容器宿主。destination/gateway都引用场景清单的节点和网卡；网关须与终端同网、至少两个接口且直连目标网段。仅生成目标节点地址的 `/32` 路由，不接受CIDR、默认路由、任意网关、额外命令或容器地址。

例如client终端的声明引用清单ID，不在配置中接收任意宿主地址：

```json
{
  "routes": [{
    "destination": {"node": "server", "interface": "eth0"},
    "gateway": {"node": "middle", "interface": "eth0"},
    "interface": "eth0"
  }],
  "flows": [{
    "source": {"node": "client", "interface": "eth0"},
    "destination": {"node": "server", "interface": "eth0"},
    "protocol": "tcp", "ports": [80], "reason": "课程HTTP访问"
  }]
}
```

server需声明经middle另一张网卡返回client的对应窄路由/入站流，middle仍需原转发白名单；单端设置不代表双向可通。直连DNS/NTP也需明确终端访问流；不自动修改resolv.conf或同步系统时间，不代表AD DNS/时间完成。

终端先关闭转发、安装默认拒绝规则，再配置接口和窄路由；IPv6仍禁通。规则只接受明确源/目的/协议/端口及有状态返回。已有主路由只允许精确的计划直连和静态主机路由；额外出口、改写网关、多路径、额外源/标志拒绝，不清空或替换原路由。重复精确路由只读确认，不重复添加。服务/容器动作前的现场指纹包含路由，缺失或漂移不能沿用历史成功记录。

## 仅补记已完成网络操作的对账

operation-status现在列出每个效果步骤的recorded/unknown，不返回任意命令或工具原始输出。原 `network-proof.json` 内容保持兼容，新增独立逐操作证明，避免新UUID破坏同内容配置重用。

新的来宾内显式入口：

```text
python3 /usr/local/lib/ctflab/ctflab_guest_agent.py --reconcile-network <原网络操作UUID>
```

只在已标记、DMI/实例/代次/策略一致的专用Linux QEMU来宾内可用。它不执行ip/nft/systemctl写命令，仅核验：唯一未决操作确为network-apply、完整步骤账本、匹配该UUID的证明、当前接口/转发/规则/路由、DNS/时间配置与摘要。全部符合后保留对账决策，补记末尾结果或network-proof效果结果；网络/服务验收仍false。

配置未完成、缺步骤、现场漂移、旧证明/他人UUID或没有逐操作证明的历史未知操作，均拒绝结清，不重放或删除。不能用它自动恢复半配置网络、OCI装载或宿主LocalService未知记录；宿主仍需只读查询并走原恢复核验流程。没有把此入口接成桌面自动修复。

## 当前仍缺

实际Linux来宾的应通/禁通、DNS/服务、Docker及冷重置，镜像自动入客与更广OCI格式、Docker半装载/卷恢复、D02容器跨网、多跳/多网卡终端、部分网络配置修复仍未完成。远程显示/租约、最终安装/启动器/在线更新、外部Kali→Windows→AD、真实课程及隔离分析器等沿用43项台账。已有Windows Smoke不重做；缺镜像/SSH/签名证书的既有回答不重复索要。

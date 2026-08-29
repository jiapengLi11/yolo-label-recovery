# Label Review Collaboration Platform / 多人审核协作平台

[中文主说明](../docs/COLLABORATION_PLATFORM.md) | [Project README](../README.md)

This directory turns the offline review queue into a multi-user, auditable web workflow. It has been validated with two independent reviewer accounts on a trusted LAN.

本目录把离线审核队列转换为多人可登录、可追溯的 Web 审核流程，并已在可信局域网中用两个独立账号完成同时审核验证。

![Real review dashboard](../docs/assets/platform-dashboard.png)

<p>
  <img src="../docs/assets/platform-review.png" width="49%" alt="Real review task">
  <img src="../docs/assets/platform-admin.png" width="49%" alt="Account administration">
</p>

## Components / 目录

- `backend/`: Spring Boot 4 REST API, JWT/RBAC, project membership, task leasing, audit and Flyway.
- `frontend/`: Vue 3 + TypeScript review workspace with heartbeat and constrained Chinese decisions.
- `tools/import_review_queue.py`: bounded, idempotent bridge for queues and historical desktop decisions.
- `tools/capture_platform_screenshots.mjs`: dependency-free Chrome DevTools documentation capture.
- `docker-compose.yml`: MySQL, API and Nginx-hosted frontend.
- `campus-deploy/`: Windows and trusted-LAN deployment scripts with Git-ignored local configuration.

## Review ergonomics / 审核交互

- The left rail groups every candidate box from the current image and shows pending, claimed, completed and escalated states.
- Decision buttons save immediately and automatically advance to the next candidate in the current image, then to the next image. This keeps the high-frequency review path to one click.
- A reviewer can revise their own completed decision; administrators may correct any completed decision. Every revision is version-checked and audited.
- Keyboard controls: `1/2/3` immediately save a decision and advance, `N` moves from a completed/historical item, `Shift+N` moves to the next image, `R` releases an unreviewed task, and `?` opens the shortcut card.
- Review images default to fit the available canvas and can switch to original pixels, zoom from 50% to 400%, or enter fullscreen. Use `0`, `+` and `-` for quick image control.
- A visible lease countdown, heartbeat state and browser network state make task ownership failures observable instead of silent.
- “My recent reviews” returns only the current reviewer's records in the selected project and reopens a completed item for version-checked, audited correction.

左侧列表按图片聚合展示全部候选框；主流程点击决定后立即保存，优先自动进入本图下一框，本图完成后自动进入下一图。租约倒计时、心跳和网络状态均可见；“我的最近审核”只展示当前账号在当前项目中的记录，可回到原图进行带版本校验和审计留痕的纠错。审核图默认以 88% 舒适比例适应画布，并支持原始尺寸、50%-400% 缩放和全屏查看。

The UI-library decision is documented in [ADR 0004](../docs/adr/0004-custom-review-workbench-over-element-plus.md): the image-first workbench stays custom, while commodity administration screens may adopt components selectively when measurements justify the dependency.

## Docker deployment / Docker 部署

![Running review workspace](../docs/assets/platform-review-workspace.png)

The image above is a capture of the running application with a real review visual and seeded collaboration records, not a mockup. Additional login and administration screenshots are available in [COLLABORATION_PLATFORM.md](../docs/COLLABORATION_PLATFORM.md).

```powershell
cd platform
Copy-Item .env.example .env
# Edit passwords, JWT secret and REVIEW_PACKAGE_DIR.
docker compose up -d --build
```

Then open `http://localhost:8088`. Full architecture, deployment and API documentation is in [COLLABORATION_PLATFORM.md](../docs/COLLABORATION_PLATFORM.md).

## Trusted LAN deployment / 校园网或局域网部署

Build the frontend and JAR, create the ignored `campus-deploy/campus.local.env`, then use the start/status/stop scripts. MySQL may run on the host, in VMware or on another LAN machine.

构建前端和 JAR 后，在 `campus-deploy/campus.local.env` 中填写仅本机使用的配置，再通过启动、状态和停止脚本管理平台。详细步骤见 [campus-deploy/README.md](campus-deploy/README.md)。

Production-scale validation imported `30,183` tasks and migrated `4,465` historical decisions. These figures validate workflow scale and migration behavior, not detector accuracy or maximum concurrency.

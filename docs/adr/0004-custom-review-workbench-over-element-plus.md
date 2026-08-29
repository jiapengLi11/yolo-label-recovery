# ADR 0004: Keep the focused review workbench instead of migrating to Element Plus

- Status: Accepted
- Date: 2026-08-29

## Context

The review client is an image-first workbench rather than a general CRUD console. Its critical interactions are the image canvas, image-grouped candidate rail, one-click constrained decisions, keyboard navigation, visible lease state and correction workflow. The existing Vue 3 components are small, typed and already validated with real reviewers.

Element Plus would improve commodity forms, tables and dialogs, but a full migration would also replace the established visual hierarchy, increase the JavaScript/CSS bundle, introduce theme overrides and create regression risk in the highest-value review path.

## Decision

Keep the custom review workbench and add dependencies only when a concrete component removes more complexity than it introduces. This iteration therefore implements one-click review with automatic advance, lease/network status, reviewer-scoped recent-decision correction and responsive image controls with native Vue and CSS.

The administration area remains a candidate for selective component adoption if it grows into pagination-heavy user, project or audit tables. Selective adoption must be measured by bundle impact, accessibility behavior and regression tests; it is not a default rewrite.

## Consequences

- The primary workflow keeps its recognizable, compact interaction model.
- The production bundle stays dependency-light and can be deployed as static files inside the Spring Boot JAR.
- The team owns accessibility and component behavior in the custom workbench.
- Future UI-library adoption must be incremental and evidence-driven.

## 中文摘要

本平台核心是图像优先的高密度审核工作台，而不是普通后台管理系统。当前 Vue 组件已经在真实多人审核中验证，整体迁移 Element Plus 会带来主题覆盖、包体积和关键路径回归成本。因此本轮保留自研工作台，主流程采用“一键决定并自动前进”，并补充租约/网络状态、最近审核纠错和图片查看能力；只有当管理后台出现复杂表格、分页和弹窗需求时，才评估按需引入组件库。

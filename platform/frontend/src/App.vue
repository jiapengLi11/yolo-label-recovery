<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, clearToken, login, saveToken, token, visualBlob } from './api'
import type { Decision, Progress, Project, ReviewTask, Role, User } from './api'

const currentUser = ref<User | null>(null)
const projects = ref<Project[]>([])
const selectedProject = ref<Project | null>(null)
const progress = ref<Progress | null>(null)
const task = ref<ReviewTask | null>(null)
const visualUrl = ref('')
const comment = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')
const loginForm = ref({ username: '', password: '' })
const userForm = ref({ username: '', password: '', displayName: '', role: 'REVIEWER' as Role })
const memberUsername = ref('')
const showAdmin = ref(false)
let heartbeatTimer: number | undefined

const percent = computed(() => Math.round((progress.value?.completionRate ?? 0) * 100))
const leaseText = computed(() => task.value ? new Date(task.value.leaseUntil).toLocaleTimeString('zh-CN') : '--')

const decisionOptions = computed<{ value: Decision; label: string; tone: string }[]>(() => {
  const recommended = task.value?.recommendedAction ?? ''
  const positive = recommended.includes('replace')
    ? { value: 'ACCEPT_REPLACE_GT' as Decision, label: '替换原框', tone: 'primary' }
    : recommended.includes('eval')
      ? { value: 'ACCEPT_EVAL_LABEL' as Decision, label: '确认评估标签', tone: 'primary' }
      : { value: 'ACCEPT_ADD' as Decision, label: '补入标签', tone: 'primary' }
  return [
    positive,
    { value: 'REJECT', label: '拒绝候选', tone: 'danger' },
    { value: 'UNCERTAIN', label: '标记疑难', tone: 'muted' },
  ]
})

async function bootstrap() {
  if (!token()) return
  try {
    currentUser.value = await api.me()
    projects.value = await api.projects()
    if (projects.value.length) await selectProject(projects.value[0])
  } catch (reason) {
    logout()
    error.value = message(reason)
  }
}

async function submitLogin() {
  busy.value = true
  error.value = ''
  try {
    const response = await login(loginForm.value.username, loginForm.value.password)
    saveToken(response.accessToken)
    currentUser.value = response.user
    projects.value = await api.projects()
    if (projects.value.length) await selectProject(projects.value[0])
  } catch (reason) {
    error.value = message(reason)
  } finally {
    busy.value = false
  }
}

async function selectProject(project: Project) {
  if (task.value && selectedProject.value?.id !== project.id) {
    error.value = '请先释放或完成当前任务，再切换项目。'
    return
  }
  selectedProject.value = project
  await refreshProgress()
}

async function refreshProgress() {
  if (!selectedProject.value) return
  progress.value = await api.progress(selectedProject.value.id)
}

async function claimNext() {
  if (!selectedProject.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const claimed = await api.claim(selectedProject.value.id)
    if (!claimed) {
      notice.value = '当前没有可领取任务。'
      return
    }
    task.value = claimed
    await loadVisual(claimed)
    startHeartbeat()
  } catch (reason) {
    error.value = message(reason)
  } finally {
    busy.value = false
  }
}

async function decide(decision: Decision) {
  if (!task.value) return
  busy.value = true
  error.value = ''
  try {
    await api.decide(task.value, decision, comment.value)
    clearTask()
    comment.value = ''
    await refreshProgress()
    notice.value = '决定已保存，正在领取下一条。'
    await claimNext()
  } catch (reason) {
    error.value = message(reason)
  } finally {
    busy.value = false
  }
}

async function releaseTask() {
  if (!task.value) return
  busy.value = true
  try {
    await api.release(task.value.id)
    clearTask()
    await refreshProgress()
    notice.value = '任务已释放，其他审核员可以继续领取。'
  } catch (reason) {
    error.value = message(reason)
  } finally {
    busy.value = false
  }
}

async function createUser() {
  busy.value = true
  error.value = ''
  try {
    await api.createUser(userForm.value)
    userForm.value = { username: '', password: '', displayName: '', role: 'REVIEWER' }
    notice.value = '协作账号已创建。'
  } catch (reason) {
    error.value = message(reason)
  } finally {
    busy.value = false
  }
}

async function assignMember() {
  if (!selectedProject.value || !memberUsername.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    await api.assignMember(selectedProject.value.id, memberUsername.value.trim())
    notice.value = `已将 ${memberUsername.value.trim()} 分配到 ${selectedProject.value.name}。`
    memberUsername.value = ''
  } catch (reason) {
    error.value = message(reason)
  } finally {
    busy.value = false
  }
}

async function loadVisual(nextTask: ReviewTask) {
  revokeVisual()
  visualUrl.value = await visualBlob(nextTask)
}

function startHeartbeat() {
  stopHeartbeat()
  heartbeatTimer = window.setInterval(async () => {
    if (!task.value) return
    try {
      task.value = await api.heartbeat(task.value.id)
    } catch (reason) {
      error.value = message(reason)
      clearTask()
    }
  }, 60_000)
}

function stopHeartbeat() {
  if (heartbeatTimer) window.clearInterval(heartbeatTimer)
  heartbeatTimer = undefined
}

function clearTask() {
  task.value = null
  stopHeartbeat()
  revokeVisual()
}

function revokeVisual() {
  if (visualUrl.value) URL.revokeObjectURL(visualUrl.value)
  visualUrl.value = ''
}

function logout() {
  clearTask()
  clearToken()
  currentUser.value = null
  projects.value = []
  selectedProject.value = null
  progress.value = null
}

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : '发生未知错误'
}

watch(selectedProject, () => { error.value = ''; notice.value = '' })
onMounted(bootstrap)
onBeforeUnmount(() => { stopHeartbeat(); revokeVisual() })
</script>

<template>
  <main v-if="!currentUser" class="login-shell">
    <section class="login-story">
      <div class="eyebrow">LABEL RECOVERY / COLLABORATION</div>
      <h1>让每一个补标决定<br><span>可领取、可追溯、可复现</span></h1>
      <p>面向 Multi-Teacher 漏标恢复的多人审核工作台。任务租约防止重复劳动，角色权限控制操作边界，审计日志记录每一次决定。</p>
      <div class="story-grid">
        <div><strong>6</strong><span>单类别 Teacher</span></div>
        <div><strong>4</strong><span>GT/AUTO 状态空间</span></div>
        <div><strong>100%</strong><span>决策审计留痕</span></div>
      </div>
    </section>
    <form class="login-card" @submit.prevent="submitLogin">
      <div class="brand-mark">矿安标注协作台</div>
      <h2>进入审核任务</h2>
      <label>账号<input v-model="loginForm.username" autocomplete="username" required placeholder="reviewer01"></label>
      <label>密码<input v-model="loginForm.password" autocomplete="current-password" type="password" required placeholder="至少 12 位"></label>
      <p v-if="error" class="message error">{{ error }}</p>
      <button class="button primary wide" :disabled="busy">{{ busy ? '正在验证...' : '登录协作台' }}</button>
      <small>ADMIN 管理项目与账号，REVIEWER 领取任务，AUDITOR 查看审计。</small>
    </form>
  </main>

  <main v-else class="workspace">
    <header class="topbar">
      <div><div class="eyebrow">MULTI-TEACHER QA</div><h1>矿安标注协作台</h1></div>
      <div class="identity">
        <span class="role">{{ currentUser.role }}</span>
        <div><strong>{{ currentUser.displayName }}</strong><small>@{{ currentUser.username }}</small></div>
        <button class="link-button" @click="logout">退出</button>
      </div>
    </header>

    <section class="project-strip">
      <button v-for="project in projects" :key="project.id" class="project-tab" :class="{ active: selectedProject?.id === project.id }" @click="selectProject(project)">
        <span class="status-dot"></span><strong>{{ project.name }}</strong><small>{{ project.status }}</small>
      </button>
      <p v-if="!projects.length" class="empty">尚未创建项目，请由管理员导入审核队列。</p>
    </section>

    <section v-if="selectedProject && progress" class="metrics">
      <article><span>总候选</span><strong>{{ progress.total.toLocaleString() }}</strong></article>
      <article><span>待审核</span><strong>{{ progress.pending.toLocaleString() }}</strong></article>
      <article><span>协作占用</span><strong>{{ progress.claimed }}</strong></article>
      <article><span>疑难升级</span><strong>{{ progress.escalated }}</strong></article>
      <article class="completion"><div><span>完成率</span><strong>{{ percent }}%</strong></div><div class="bar"><i :style="{ width: `${percent}%` }"></i></div></article>
    </section>

    <p v-if="error" class="message error banner">{{ error }}</p>
    <p v-if="notice" class="message notice banner">{{ notice }}</p>

    <section class="review-layout">
      <article class="canvas-panel">
        <div class="panel-head">
          <div><span class="live-dot"></span>{{ task ? '任务租约生效中' : '等待领取' }}</div>
          <span v-if="task">租约至 {{ leaseText }}</span>
        </div>
        <div v-if="task" class="image-stage">
          <img v-if="visualUrl" :src="visualUrl" :alt="task.imageName">
          <div v-else class="loader">正在加载真实审核图...</div>
        </div>
        <div v-else class="empty-stage">
          <span>R</span><h2>准备好开始审核了吗？</h2><p>系统会原子领取一条候选，其他审核员不会拿到同一任务。</p>
          <button class="button primary" :disabled="busy || !selectedProject || currentUser.role === 'AUDITOR'" @click="claimNext">领取下一条任务</button>
        </div>
      </article>

      <aside class="decision-panel">
        <template v-if="task">
          <div class="candidate-id">{{ task.candidateId }}</div>
          <h2>{{ task.className }} <span>{{ (task.confidence * 100).toFixed(1) }}%</span></h2>
          <dl>
            <div><dt>状态枚举</dt><dd>{{ task.caseCode }}</dd></div>
            <div><dt>建议动作</dt><dd>{{ task.recommendedAction }}</dd></div>
            <div><dt>数据划分</dt><dd>{{ task.split }}</dd></div>
            <div><dt>图像名称</dt><dd class="wrap">{{ task.imageName }}</dd></div>
          </dl>
          <label class="comment">审核备注<textarea v-model="comment" maxlength="1000" placeholder="可选：记录接受或拒绝依据"></textarea></label>
          <div class="decision-actions">
            <button v-for="option in decisionOptions" :key="option.value" class="button" :class="option.tone" :disabled="busy" @click="decide(option.value)">{{ option.label }}</button>
          </div>
          <button class="link-button release" :disabled="busy" @click="releaseTask">暂不处理，释放任务</button>
        </template>
        <template v-else>
          <div class="guide-number">01</div><h2>领取后再判断</h2><p>真实图像、GT 框和 AUTO 框会在同一张审核图里显示。按钮由候选建议动作动态约束，降低误操作风险。</p>
          <div class="guide-number">02</div><h2>心跳自动续租</h2><p>页面每 60 秒续租一次；关闭页面后租约到期，任务自动回到公共队列。</p>
        </template>
      </aside>
    </section>

    <section v-if="currentUser.role === 'ADMIN'" class="admin-drawer">
      <button class="drawer-toggle" @click="showAdmin = !showAdmin">{{ showAdmin ? '收起账号管理' : '管理员：创建协作账号' }}</button>
      <form v-if="showAdmin" @submit.prevent="createUser">
        <input v-model="userForm.username" required maxlength="64" placeholder="登录账号">
        <input v-model="userForm.displayName" required maxlength="100" placeholder="显示名称">
        <input v-model="userForm.password" required minlength="12" type="password" placeholder="临时密码（至少 12 位）">
        <select v-model="userForm.role"><option>REVIEWER</option><option>AUDITOR</option><option>ADMIN</option></select>
        <button class="button primary" :disabled="busy">创建账号</button>
      </form>
      <form v-if="showAdmin" class="member-assign" @submit.prevent="assignMember">
        <input v-model="memberUsername" required maxlength="64" placeholder="输入已有账号">
        <span>分配到：{{ selectedProject?.name || '请先选择项目' }}</span>
        <button class="button muted" :disabled="busy || !selectedProject">分配项目成员</button>
      </form>
    </section>
  </main>
</template>

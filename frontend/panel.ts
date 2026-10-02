import { LitElement, html, svg, nothing, type PropertyValues } from "lit";
import { styles } from "./styles";
import { messages, type MessageKey } from "./i18n";
import type { Camera, Hass, Job, Mode, Scan, ScheduleMode, State, Video } from "./types";

type Tab = "overview" | "cameras" | "schedules" | "jobs" | "gallery" | "settings";
const modes: Mode[] = ["weekly", "monthly", "yearly", "custom"];
const defaultCamera = (): Camera => ({
  name: "", source_dir: "", prefix: "", timestamp_format: "%Y%m%d_%H%M%S",
  fps: 12, yearly_fps: 24, crf: 23, resolution: "source", timeout: 3600,
  schedules: { weekly: { enabled: false, time: "00:15" }, monthly: { enabled: false, time: "00:30" }, yearly: { enabled: false, time: "01:00" } },
});
const icons: Record<string, ReturnType<typeof svg>> = {
  video: svg`<rect x="3" y="5" width="14" height="14" rx="3"/><path d="m17 10 4-3v10l-4-3"/>`,
  clock: svg`<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>`,
  camera: svg`<path d="M8 5h8l2 3h3v12H3V8h3z"/><circle cx="12" cy="13" r="4"/>`,
  grid: svg`<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>`,
  library: svg`<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M6 3h12M4 5h16m-6 7 4 3-4 3z"/>`,
  settings: svg`<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="9" cy="18" r="2"/>`,
  plus: svg`<path d="M12 5v14M5 12h14"/>`, play: svg`<path d="m9 5 11 7-11 7z"/>`,
  download: svg`<path d="M12 3v12m-5-5 5 5 5-5M5 16v5h14v-5"/>`,
  trash: svg`<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>`,
  close: svg`<path d="m6 6 12 12M6 18 18 6"/>`,
  lock: svg`<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>`,
  menu: svg`<path d="M3 6h18M3 12h18M3 18h18"/>`,
};
const icon = (name: string) => svg`<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] ?? icons.video}</svg>`;

export class TimelapsePanel extends LitElement {
  static styles = styles;
  static properties = {
    hass: { attribute: false }, narrow: { type: Boolean }, panel: { attribute: false },
    state: { state: true }, tab: { state: true }, language: { state: true }, error: { state: true },
    notice: { state: true }, busy: { state: true }, dialog: { state: true }, draft: { state: true },
    scanResult: { state: true }, selectedCamera: { state: true }, selectedMode: { state: true },
    startDate: { state: true }, endDate: { state: true }, cameraFilter: { state: true }, modeFilter: { state: true },
    playing: { state: true }, videoUrl: { state: true },
  };
  declare hass?: Hass;
  narrow = false;
  declare panel: object;
  declare state?: State;
  tab: Tab = "overview";
  language = "auto";
  error = "";
  notice = "";
  busy = false;
  dialog = "";
  draft = defaultCamera();
  declare scanResult?: Scan;
  selectedCamera = "all";
  selectedMode: Mode = "weekly";
  startDate = "";
  endDate = "";
  cameraFilter = "all";
  modeFilter = "all";
  declare playing?: Video;
  videoUrl = "";
  private unsubscribe?: () => void;
  private connection?: Hass["connection"];
  private subscriptionGeneration = 0;
  private toastTimer?: ReturnType<typeof setTimeout>;
  private scheduleDrafts = new Map<string, Camera["schedules"]>();
  private settingsDraft?: State["settings"];
  private reconnecting = false;

  get admin() { return this.hass?.user?.is_admin === true; }
  get locale() { return this.language === "auto" ? this.hass?.language ?? "en" : this.language; }
  t(key: MessageKey) { return messages(this.locale)[key]; }

  protected updated(changed: PropertyValues) {
    if (changed.has("hass") && this.hass && this.connection !== this.hass.connection) void this.connect();
    const modal = this.renderRoot.querySelector("dialog");
    if (this.dialog && modal && !modal.open) modal.showModal();
  }
  connectedCallback() {
    super.connectedCallback();
    if (this.hass) void this.connect();
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    this.subscriptionGeneration++;
    this.unsubscribe?.();
    this.unsubscribe = undefined;
    this.connection = undefined;
    clearTimeout(this.toastTimer);
  }
  private async connect() {
    if (!this.hass || this.reconnecting) return;
    this.reconnecting = true;
    const generation = ++this.subscriptionGeneration;
    this.unsubscribe?.();
    this.connection = this.hass.connection;
    try {
      const unsubscribe = await this.connection.subscribeMessage<State>((state) => { this.state = state; }, { type: "ha_tgen/subscribe" });
      if (generation !== this.subscriptionGeneration || !this.isConnected) unsubscribe();
      else this.unsubscribe = unsubscribe;
      this.error = "";
    } catch (error) { this.fail(error); this.connection = undefined; }
    finally { this.reconnecting = false; }
  }
  private fail(error: unknown) {
    this.error = (error as { message?: string })?.message ?? String(error);
  }
  private toast(message: string) {
    this.notice = message;
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => { this.notice = ""; }, 4500);
  }
  private async manage<T = unknown>(action: string, data: object): Promise<T> {
    if (!this.hass) throw new Error(this.t("connecting"));
    return this.hass.connection.sendMessagePromise<T>({ type: "ha_tgen/manage", action, data });
  }
  private async operation(work: () => Promise<void>) {
    if (this.busy) return;
    this.busy = true; this.error = "";
    try { await work(); } catch (error) { this.fail(error); }
    finally { this.busy = false; }
  }
  private closeDialog() { this.dialog = ""; this.playing = undefined; this.videoUrl = ""; this.error = ""; }
  private openCamera(camera?: Camera) {
    this.draft = camera ? structuredClone(camera) : defaultCamera();
    this.scanResult = undefined; this.error = ""; this.dialog = "camera";
  }
  private openGenerate(id = "all") { this.selectedCamera = id; this.error = ""; this.dialog = "generate"; }
  private changeDraft(key: keyof Camera, value: string | number) {
    this.draft = { ...this.draft, [key]: value };
    this.scanResult = undefined;
  }
  private async scan() {
    await this.operation(async () => { this.scanResult = await this.manage<Scan>("preview", this.draft); });
  }
  private async saveCamera() {
    await this.operation(async () => {
      await this.manage("save_camera", this.draft); this.closeDialog(); this.toast(this.t("saved"));
    });
  }
  private async generate() {
    await this.operation(async () => {
      const ids = this.selectedCamera === "all" ? this.state!.cameras.map(c => c.id!) : [this.selectedCamera];
      await this.manage("generate", { camera_ids: ids, mode: this.selectedMode, start_date: this.startDate, end_date: this.endDate });
      this.closeDialog(); this.tab = "jobs"; this.toast(this.t("added"));
    });
  }
  private async removeCamera(camera: Camera) {
    if (!window.confirm(this.t("deleteCameraConfirm"))) return;
    await this.operation(async () => { await this.manage("delete_camera", { id: camera.id }); this.toast(this.t("saved")); });
  }
  private async removeVideo(video: Video) {
    if (!window.confirm(this.t("deleteVideoConfirm"))) return;
    await this.operation(async () => { await this.manage("delete_video", { id: video.id }); });
  }
  private async getVideoUrl(id: string) {
    return (await this.hass!.connection.sendMessagePromise<{ url: string }>({ type: "ha_tgen/video_url", video_id: id })).url;
  }
  private async watch(video: Video) {
    await this.operation(async () => {
      this.videoUrl = await this.getVideoUrl(video.id); this.playing = video; this.dialog = "player";
    });
  }
  private async renewVideo() {
    if (!this.playing) return;
    const element = this.renderRoot.querySelector("video");
    if (!element) return;
    const seek = element.currentTime, paused = element.paused;
    try {
      this.videoUrl = await this.getVideoUrl(this.playing.id);
      await this.updateComplete;
      element.addEventListener("loadedmetadata", () => { element.currentTime = seek; if (!paused) void element.play(); }, { once: true });
      element.load();
    } catch (error) { this.fail(error); }
  }
  private async download(video: Video) {
    await this.operation(async () => {
      const anchor = document.createElement("a");
      anchor.href = await this.getVideoUrl(video.id);
      anchor.download = `timelapse_${video.start_date}_${video.end_date}_${video.id.slice(0, 8)}.mp4`;
      anchor.click();
    });
  }
  private async retry(job: Job) {
    await this.operation(async () => {
      await this.manage("retry", { id: job.id });
      this.toast(this.t("added"));
    });
  }
  private date(value: string) {
    // These are HA-local calendar dates, not UTC instants to convert a second time.
    return new Intl.DateTimeFormat(this.locale, { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${value.slice(0, 10)}T12:00:00Z`));
  }
  private size(bytes: number) { return `${(bytes / 1048576).toFixed(1)} MB`; }
  private duration(seconds: number) { return `${Math.floor(seconds / 60)}:${Math.round(seconds % 60).toString().padStart(2, "0")}`; }

  private renderVideo(video: Video) {
    return html`<article class="card">
      <button class="video-cover" aria-label="${this.t("play")}: ${video.camera_name}" @click=${() => this.watch(video)}>
        ${video.latest ? html`<span class="cover-label">${this.t("latest")}</span>` : nothing}
        <span class="play">${icon("play")}</span><span class="cover-duration">${this.duration(video.duration)}</span>
      </button>
      <div class="card-body"><h3>${video.camera_name}</h3><div class="caption">${this.t(video.mode)}</div>
        <div class="caption">${this.date(video.start_date)} – ${this.date(video.end_date)}</div>
        <div class="metadata"><span>${video.frames.toLocaleString(this.locale)} ${this.t("photos")}</span><span>${video.fps} FPS</span><span>${this.size(video.size)}</span></div>
        <div class="card-actions"><button class="secondary" @click=${() => this.watch(video)}>${icon("play")}${this.t("play")}</button>
          <button class="icon-button" aria-label=${this.t("download")} title=${this.t("download")} @click=${() => this.download(video)}>${icon("download")}</button>
          ${this.admin ? html`<button class="icon-button" aria-label=${this.t("deleteVideo")} title=${this.t("deleteVideo")} @click=${() => this.removeVideo(video)}>${icon("trash")}</button>` : nothing}
        </div></div></article>`;
  }
  private renderEmpty(kind: "cameras" | "videos") {
    const cameras = kind === "cameras";
    return html`<div class="empty">${icon(cameras ? "camera" : "video")}<h3>${this.t(cameras ? "noCameras" : "noVideos")}</h3>
      <p>${this.t(cameras ? "noCamerasHint" : "noVideosHint")}</p>
      ${this.admin ? html`<button class="primary" @click=${() => cameras || !this.state!.cameras.length ? this.openCamera() : this.openGenerate()}>${icon("plus")}${this.t(cameras || !this.state!.cameras.length ? "addCamera" : "newVideo")}</button>` : nothing}</div>`;
  }
  private renderOverview() {
    const state = this.state!;
    const pending = state.jobs.filter(j => ["queued", "running"].includes(j.status)).length;
    return html`<div class="stats">${[["camera", state.cameras.length, "sources"], ["video", state.videos.length, "videos"], ["clock", pending, "queue"]].map(([name, value, label]) => html`<div class="stat"><div class="stat-icon">${icon(String(name))}</div><div><strong>${value}</strong><span>${this.t(label as MessageKey)}</span></div></div>`)}</div>
      ${this.admin ? html`<section class="hero"><div><h2>${this.t("newVideo")}</h2><p>${this.t("tip")}</p></div>${icon("clock")}<button class="primary" @click=${() => state.cameras.length ? this.openGenerate() : this.openCamera()}>${icon("plus")}${this.t(state.cameras.length ? "newVideo" : "addCamera")}</button></section>` : nothing}
      <div class="section-head"><h2>${this.t("recent")}</h2><button class="text-button" @click=${() => { this.tab = "gallery"; }}>${this.t("viewAll")} →</button></div>
      ${state.videos.length ? html`<div class="grid">${state.videos.slice(0, 3).map(video => this.renderVideo(video))}</div>` : this.renderEmpty("videos")}`;
  }
  private renderCameras() {
    return html`<div class="section-head"><h2>${this.t("cameras")}</h2><button class="primary" @click=${() => this.openCamera()}>${icon("plus")}${this.t("addCamera")}</button></div>
      ${!this.state!.cameras.length ? this.renderEmpty("cameras") : html`<div class="grid camera-grid">${this.state!.cameras.map(camera => html`<article class="card"><div class="card-body">
        <div class="card-top"><div class="stat-icon">${icon("camera")}</div><div><h3>${camera.name}</h3><span class="caption">${camera.fps} FPS · ${camera.resolution === "source" ? this.t("original") : camera.resolution}</span></div></div>
        <code class="path">${camera.source_dir}</code><code class="path">${camera.prefix}${camera.timestamp_format}</code>
        <details><summary>${this.t("cameraId")}</summary><code class="path">${camera.id}</code></details>
        <div class="card-actions"><button class="primary" @click=${() => this.openGenerate(camera.id)}>${icon("play")}${this.t("generate")}</button><button class="secondary" @click=${() => this.openCamera(camera)}>${this.t("edit")}</button><button class="icon-button" aria-label=${this.t("remove")} @click=${() => this.removeCamera(camera)}>${icon("trash")}</button></div>
      </div></article>`)}</div>`}`;
  }
  private updateSchedule(camera: Camera, mode: ScheduleMode, key: "time" | "enabled", value: string | boolean) {
    const draft = structuredClone(this.scheduleDrafts.get(camera.id!) ?? camera.schedules);
    draft[mode] = { ...draft[mode], [key]: value };
    this.scheduleDrafts.set(camera.id!, draft); this.requestUpdate();
  }
  private renderSchedules() {
    return html`<div class="section-head"><div><h2>${this.t("schedules")}</h2><p class="caption">${this.t("scheduleHint")} · ${this.state!.timezone}</p></div></div>
      ${!this.state!.cameras.length ? this.renderEmpty("cameras") : this.state!.cameras.map(camera => {
        const schedules = this.scheduleDrafts.get(camera.id!) ?? camera.schedules;
        return html`<article class="card schedule-card"><h3>${camera.name}</h3><div class="schedule-grid">${(["weekly", "monthly", "yearly"] as ScheduleMode[]).map(mode => html`<div class="schedule-block">
          <label class="toggle"><span>${this.t(mode)}</span><input type="checkbox" aria-label="${camera.name} ${this.t(mode)}" .checked=${schedules[mode].enabled} @change=${(event: Event) => this.updateSchedule(camera, mode, "enabled", (event.target as HTMLInputElement).checked)}></label>
          <p class="help">${this.t(`${mode}Hint` as MessageKey)}</p><input class="spaced" type="time" aria-label="${camera.name} ${this.t(mode)} ${this.t("timezone")}" .value=${schedules[mode].time} @input=${(event: Event) => this.updateSchedule(camera, mode, "time", (event.target as HTMLInputElement).value)}></div>`)}</div>
          <button class="secondary" ?disabled=${this.busy} @click=${() => this.operation(async () => { await this.manage("save_camera", { ...camera, schedules }); this.scheduleDrafts.delete(camera.id!); this.toast(this.t("scheduleSaved")); })}>${this.t("saveSchedule")}</button></article>`;
      })}`;
  }
  private renderJobs() {
    return html`<div class="section-head"><h2>${this.t("jobs")}</h2><button class="primary" ?disabled=${!this.state!.cameras.length} @click=${() => this.openGenerate()}>${icon("plus")}${this.t("newVideo")}</button></div>
      ${this.state!.jobs.length ? this.state!.jobs.map(job => html`<article class="job"><div class="job-head"><div><h3>${job.camera_name} · ${this.t(job.mode)}</h3><p>${this.date(job.start_date)} – ${this.date(job.end_date)}</p></div><span class="badge ${job.status}">${this.t(job.status as MessageKey)}</span></div>
        ${job.status === "running" ? html`<progress max=${job.total || 1} value=${job.processed}></progress><p>${job.processed.toLocaleString(this.locale)} / ${job.total.toLocaleString(this.locale)} ${this.t("processed")}</p>` : nothing}
        <div class="card-actions">${["queued", "running"].includes(job.status) ? html`<button class="secondary" @click=${() => this.operation(async () => { await this.manage("cancel", { id: job.id }); })}>${this.t("stop")}</button>` : nothing}
          ${["failed", "cancelled", "interrupted"].includes(job.status) && this.state!.cameras.some(c => c.id === job.camera_id) ? html`<button class="secondary" @click=${() => this.retry(job)}>${this.t("retry")}</button>` : nothing}
          ${job.video_id && this.state!.videos.some(v => v.id === job.video_id) ? html`<button class="secondary" @click=${() => this.watch(this.state!.videos.find(v => v.id === job.video_id)!)}>${icon("play")}${this.t("play")}</button>` : nothing}</div>
        <details><summary>${this.t("details")} · ${job.frames} ${this.t("photos")} · ${job.skipped} ${this.t("ignored")}</summary><code class="path">${job.id}</code>${job.error ? html`<p class="alert">${job.error}</p>` : nothing}
          ${job.warnings.length ? html`<ul>${job.warnings.map(w => html`<li>${w}</li>`)}</ul>` : html`<p>${this.t("noDetails")}</p>`}</details></article>`) : html`<div class="empty">${icon("clock")}<h3>${this.t("noJobs")}</h3></div>`}`;
  }
  private renderGallery() {
    const names = new Map(this.state!.cameras.map(c => [c.id, c.name]));
    for (const video of this.state!.videos) names.set(video.camera_id, video.camera_name);
    const filtered = this.state!.videos.filter(v => (this.cameraFilter === "all" || v.camera_id === this.cameraFilter) && (this.modeFilter === "all" || v.mode === this.modeFilter));
    return html`<div class="section-head"><h2>${this.t("gallery")}</h2>${this.admin ? html`<button class="primary" ?disabled=${!this.state!.cameras.length} @click=${() => this.openGenerate()}>${icon("plus")}${this.t("newVideo")}</button>` : nothing}</div>
      <div class="toolbar"><select aria-label=${this.t("selectCamera")} .value=${this.cameraFilter} @change=${(event: Event) => { this.cameraFilter = (event.target as HTMLSelectElement).value; }}><option value="all">${this.t("allCameras")}</option>${[...names].map(([id, name]) => html`<option value=${id!}>${name}</option>`)}</select>
        <select aria-label=${this.t("period")} .value=${this.modeFilter} @change=${(event: Event) => { this.modeFilter = (event.target as HTMLSelectElement).value; }}><option value="all">${this.t("allPeriods")}</option>${modes.map(mode => html`<option value=${mode}>${this.t(mode)}</option>`)}</select></div>
      ${filtered.length ? html`<div class="grid">${filtered.map(video => this.renderVideo(video))}</div>` : this.renderEmpty("videos")}`;
  }
  private renderSettings() {
    const settings = this.settingsDraft ?? this.state!.settings;
    return html`<div class="section-head"><h2>${this.t("settings")}</h2></div><form class="card settings-card" @submit=${(event: Event) => { event.preventDefault(); void this.operation(async () => { await this.manage("save_settings", settings); this.settingsDraft = undefined; this.toast(this.t("saved")); }); }}>
      <div class="form-grid"><div class="field full"><label for="output">${this.t("output")}</label><input id="output" required .value=${settings.output_root} @input=${(event: Event) => { this.settingsDraft = { ...settings, output_root: (event.target as HTMLInputElement).value }; this.requestUpdate(); }}><p class="help">${this.t("outputHint")}</p></div>
      <div class="field full"><label for="retention">${this.t("retention")}</label><input id="retention" type="number" min="0" max="36500" step="1" required .value=${String(settings.retention_days)} @input=${(event: Event) => { this.settingsDraft = { ...settings, retention_days: Number((event.target as HTMLInputElement).value) }; this.requestUpdate(); }}><p class="help">${this.t("retentionHint")}</p></div></div>
      <details class="spaced" open><summary>${this.t("sourceRoots")}</summary>${this.state!.source_roots.map(root => html`<code class="path">${root}</code>`)}</details>
      <details class="spaced"><summary>${this.t("outputRoots")}</summary>${this.state!.output_roots.map(root => html`<code class="path">${root}</code>`)}</details>
      <div class="form-actions"><button class="primary" ?disabled=${this.busy}>${this.t("saveSettings")}</button></div></form>`;
  }
  private cameraField(key: keyof Camera, label: MessageKey, type = "text", min?: number, max?: number) {
    return html`<div class="field ${key === "source_dir" || key === "name" ? "full" : ""}"><label for=${key}>${this.t(label)}</label><input id=${key} type=${type} min=${min ?? nothing} max=${max ?? nothing} step=${type === "number" ? 1 : nothing} ?required=${key !== "prefix"} .value=${String(this.draft[key])} @input=${(event: Event) => { const value = (event.target as HTMLInputElement).value; this.changeDraft(key, type === "number" ? Number(value) : value); }}></div>`;
  }
  private renderDialog() {
    if (!this.dialog) return nothing;
    return html`<dialog class=${this.dialog === "player" ? "player-dialog" : ""} aria-label=${this.dialog === "camera" ? this.t("addCamera") : this.dialog === "player" ? this.playing!.camera_name : this.t("newVideo")} @cancel=${() => this.closeDialog()}>
      <div class="section-head"><h2>${this.dialog === "camera" ? this.t(this.draft.id ? "edit" : "addCamera") : this.dialog === "player" ? this.playing!.camera_name : this.t("newVideo")}</h2><button class="icon-button" aria-label=${this.t("close")} @click=${() => this.closeDialog()}>${icon("close")}</button></div>
      ${this.error ? html`<div class="alert" role="alert">${this.error}</div>` : nothing}
      ${this.dialog === "camera" ? html`<form @submit=${(event: Event) => { event.preventDefault(); void this.saveCamera(); }}><div class="form-grid">
        ${this.cameraField("name", "name")}${this.cameraField("source_dir", "folder")}
        <p class="help field full">${this.t("sourceHint")}</p>${this.cameraField("prefix", "prefix")}${this.cameraField("timestamp_format", "format")}
        <p class="help field full">${this.t("formatHint")}</p></div>
        <details class="spaced"><summary>${this.t("advanced")}</summary><div class="form-grid spaced">${this.cameraField("fps", "fps", "number", 1, 60)}${this.cameraField("yearly_fps", "yearlyFps", "number", 1, 60)}${this.cameraField("crf", "quality", "number", 0, 51)}${this.cameraField("timeout", "timeout", "number", 10, 86400)}
          <div class="field full"><label for="resolution">${this.t("resolution")}</label><select id="resolution" .value=${this.draft.resolution} @change=${(event: Event) => this.changeDraft("resolution", (event.target as HTMLSelectElement).value)}><option value="source">${this.t("original")}</option>${["720p", "1080p", "2160p"].map(r => html`<option value=${r}>${r}</option>`)}</select></div></div></details>
        ${this.scanResult ? html`<div class="scan-result"><strong>${this.scanResult.count.toLocaleString(this.locale)} ${this.t("matching")}</strong> · ${this.scanResult.skipped} ${this.t("ignored")}${this.scanResult.samples.map(sample => html`<code>${sample.filename} → ${sample.timestamp}</code>`)}</div>` : html`<p class="help spaced">${this.t("previewFirst")}</p>`}
        <div class="form-actions"><button class="secondary" type="button" ?disabled=${this.busy} @click=${() => this.scan()}>${this.t("scan")}</button><button class="primary" ?disabled=${this.busy || !this.scanResult}>${this.t("saveCamera")}</button></div></form>` : nothing}
      ${this.dialog === "generate" ? html`<form @submit=${(event: Event) => { event.preventDefault(); void this.generate(); }}><div class="form-grid">
        <div class="field full"><label for="generate-camera">${this.t("selectCamera")}</label><select id="generate-camera" .value=${this.selectedCamera} @change=${(event: Event) => { this.selectedCamera = (event.target as HTMLSelectElement).value; }}><option value="all">${this.t("allCameras")}</option>${this.state!.cameras.map(c => html`<option value=${c.id!}>${c.name}</option>`)}</select></div>
        <div class="field full"><label for="generate-mode">${this.t("period")}</label><select id="generate-mode" .value=${this.selectedMode} @change=${(event: Event) => { this.selectedMode = (event.target as HTMLSelectElement).value as Mode; }}>${modes.map(mode => html`<option value=${mode}>${this.t(mode)}</option>`)}</select></div>
        ${this.selectedMode === "custom" ? html`<div class="field"><label for="start-date">${this.t("start")}</label><input id="start-date" type="date" required .value=${this.startDate} @input=${(event: Event) => { this.startDate = (event.target as HTMLInputElement).value; }}></div><div class="field"><label for="end-date">${this.t("end")}</label><input id="end-date" type="date" required min=${this.startDate || nothing} .value=${this.endDate} @input=${(event: Event) => { this.endDate = (event.target as HTMLInputElement).value; }}></div><p class="help field full">${this.t("inclusive")}</p>` : nothing}</div>
        <div class="form-actions"><button class="secondary" type="button" @click=${() => this.closeDialog()}>${this.t("cancel")}</button><button class="primary" ?disabled=${this.busy || !this.state!.cameras.length}>${this.t(this.busy ? "generating" : "generate")}</button></div></form>` : nothing}
      ${this.dialog === "player" ? html`<video controls autoplay playsinline src=${this.videoUrl} @error=${() => this.renewVideo()}></video><div class="metadata"><span>${this.t(this.playing!.mode)}</span><span>${this.date(this.playing!.start_date)} – ${this.date(this.playing!.end_date)}</span></div><div class="form-actions"><button class="secondary" @click=${() => this.download(this.playing!)}>${icon("download")}${this.t("download")}</button></div>` : nothing}
    </dialog>`;
  }
  protected render() {
    const tabs: [Tab, string][] = this.admin ? [["overview", "grid"], ["cameras", "camera"], ["schedules", "clock"], ["jobs", "video"], ["gallery", "library"], ["settings", "settings"]] : [["overview", "grid"], ["gallery", "library"]];
    const active = tabs.some(([tab]) => tab === this.tab) ? this.tab : "gallery";
    return html`<div class="shell"><header><div class="brand"><button class="icon-button menu-button" aria-label="Menu" @click=${() => this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }))}>${icon("menu")}</button><div class="logo">${icon("video")}</div><div><h1>${this.t("title")}</h1><p class="subtitle">${this.t("subtitle")}</p></div></div><span class="pill">${icon("lock")}${this.t("local")}</span></header>
      <nav aria-label=${this.t("title")}>${tabs.map(([tab, name]) => html`<button class=${active === tab ? "active" : ""} aria-current=${active === tab ? "page" : nothing} @click=${() => { this.tab = tab; this.error = ""; }}>${icon(name)}${this.t(tab)}</button>`)}</nav>
      ${this.error && !this.dialog ? html`<div class="alert" role="alert">${this.error}<button class="text-button" @click=${() => this.connect()}>${this.t("reconnect")}</button></div>` : nothing}
      ${this.notice ? html`<div class="notice" role="status">${this.notice}</div>` : nothing}
      ${this.state ? active === "overview" ? this.renderOverview() : active === "cameras" ? this.renderCameras() : active === "schedules" ? this.renderSchedules() : active === "jobs" ? this.renderJobs() : active === "settings" ? this.renderSettings() : this.renderGallery() : html`<div class="loading">${this.t("connecting")}</div>`}
      <footer><span class="footer-brand">${icon("video")} HA Timelapse Generator · v0.1.0</span><label>${this.t("language")} <select aria-label=${this.t("language")} .value=${this.language} @change=${(event: Event) => { this.language = (event.target as HTMLSelectElement).value; }}><option value="auto">${this.t("automatic")}</option><option value="en">English</option><option value="tr">Türkçe</option></select></label></footer>
    </div>${this.renderDialog()}`;
  }
}
if (!customElements.get("ha-tgen-panel")) customElements.define("ha-tgen-panel", TimelapsePanel);

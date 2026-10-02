export type Mode = "weekly" | "monthly" | "yearly" | "custom";
export type ScheduleMode = Exclude<Mode, "custom">;
export interface Schedule { enabled: boolean; time: string }
export interface Camera {
  id?: string; name: string; source_dir: string; prefix: string; timestamp_format: string;
  fps: number; yearly_fps: number; crf: number; resolution: string; timeout: number;
  schedules: Record<ScheduleMode, Schedule>;
}
export interface Job {
  id: string; camera_id: string; camera_name: string; mode: Mode; status: string;
  start_date: string; end_date: string; created_at: string; finished_at?: string;
  processed: number; total: number; frames: number; skipped: number;
  warnings: string[]; error?: string; video_id?: string;
}
export interface Video {
  id: string; camera_id: string; camera_name: string; mode: Mode; start_date: string;
  end_date: string; created_at: string; frames: number; fps: number; size: number;
  duration: number; latest: boolean;
}
export interface State {
  settings: { output_root: string; retention_days: number };
  cameras: Camera[]; jobs: Job[]; videos: Video[];
  source_roots: string[]; output_roots: string[]; timezone: string;
}
export interface Scan { count: number; skipped: number; samples: { filename: string; timestamp: string }[]; warnings: string[] }
export interface Hass {
  language: string; user: { is_admin: boolean };
  connection: {
    sendMessagePromise<T>(message: object): Promise<T>;
    subscribeMessage<T>(callback: (state: T) => void, message: object): Promise<() => void>;
  };
}

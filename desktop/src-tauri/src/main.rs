#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use std::{path::PathBuf, process::Command, sync::LazyLock, time::Duration};
use tauri::Manager;
mod transport;
static BRIDGES: LazyLock<transport::Transport> = LazyLock::new(|| transport::Transport::new(8));

// 本机与远程仅选择两个固定脚本，界面不能指定程序或命令。
async fn run_bridge(
    app: tauri::AppHandle,
    run: String,
    payload: serde_json::Value,
    route: u8,
) -> Result<serde_json::Value, String> {
    if !PathBuf::from(&run).is_absolute() || payload.to_string().len() > 65536 {
        return Err("请使用本机绝对路径和有效配置。".into());
    }
    let resources = app
        .path()
        .resource_dir()
        .map_err(|_| "无法定位随包运行时。")?;
    tauri::async_runtime::spawn_blocking(move || {
        let script_name = match route {
            0 => "ctflab_desktop_bridge.py",
            1 => "ctflab_desktop_remote.py",
            2 => "ctflab_client_store.py",
            3 => "ctflab_version_bridge.py",
            _ => return Err("桥接入口不受支持。".into()),
        };
        let (python, script) = if cfg!(debug_assertions) {
            let python = std::env::var("CTFLAB_DESKTOP_PYTHON")
                .map_err(|_| "开发运行需明确设置 CTFLAB_DESKTOP_PYTHON 的绝对路径。")?;
            if !PathBuf::from(&python).is_absolute() {
                return Err("Python 必须使用绝对路径。".into());
            }
            (
                PathBuf::from(python),
                PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("../../tools")
                    .join(script_name),
            )
        } else {
            (
                resources.join("runtime/python/python.exe"),
                resources.join("runtime/tools").join(script_name),
            )
        };
        let mut cmd = Command::new(python);
        cmd.args(["-X", "utf8", "-I", "-B"]).arg(script);
        match route {
            0 => {
                cmd.args(["bridge", "--run", &run]);
            }
            1 | 3 => {
                if route == 3 {
                    cmd.arg("bridge");
                }
                cmd.args(["--config", &run]);
            }
            _ => {
                cmd.args(["--root", &run]);
            }
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW，仅隐藏桥接控制台。
        }
        let raw = serde_json::to_vec(&payload).map_err(|_| "请求格式无效。")?;
        let stdout = BRIDGES
            .execute(cmd, raw, Duration::from_secs(90), 4 * 1024 * 1024)
            .map_err(|error| error.message().to_string())?;
        serde_json::from_slice(&stdout).map_err(|_| "响应无效；现场保持不变，请读取状态。".into())
    })
    .await
    .map_err(|_| "本地桥接任务未完成。".to_string())?
}

#[tauri::command]
async fn bridge(
    app: tauri::AppHandle,
    run: String,
    payload: serde_json::Value,
) -> Result<serde_json::Value, String> {
    run_bridge(app, run, payload, 0).await
}

#[tauri::command]
async fn remote_bridge(
    app: tauri::AppHandle,
    config: String,
    payload: serde_json::Value,
) -> Result<serde_json::Value, String> {
    run_bridge(app, config, payload, 1).await
}

#[tauri::command]
async fn client_bridge(
    app: tauri::AppHandle,
    payload: serde_json::Value,
) -> Result<serde_json::Value, String> {
    // 私有根由宿主确定，界面不能传入任意状态目录。
    let root = app
        .path()
        .app_data_dir()
        .map_err(|_| "无法定位本机应用数据目录。")?
        .join("remote-client");
    run_bridge(app, root.to_string_lossy().into_owned(), payload, 2).await
}

#[tauri::command]
async fn version_bridge(
    app: tauri::AppHandle,
    config: String,
    payload: serde_json::Value,
) -> Result<serde_json::Value, String> {
    run_bridge(app, config, payload, 3).await
}

#[tauri::command]
async fn version_setup(
    app: tauri::AppHandle,
    payload: serde_json::Value,
) -> Result<serde_json::Value, String> {
    // 使用通用本机数据目录的独立子目录，避开安装目录及应用ID的卸载数据目录。
    let config = app
        .path()
        .local_data_dir()
        .map_err(|_| "无法定位本机数据目录。")?
        .join("CTFLabData")
        .join("version-manager")
        .join("manager.json");
    run_bridge(app, config.to_string_lossy().into_owned(), payload, 3).await
}

fn dialog_title(kind: &str) -> Result<&'static str, String> {
    match kind {
        "config" => Ok("选择连接配置 JSON"),
        "version_config" => Ok("选择版本库配置 JSON"),
        "release_manifest" => Ok("选择签名版本清单 JSON"),
        "release_keys" => Ok("选择已核对发布者的公钥 JSON"),
        "identity" => Ok("选择 SSH 身份文件"),
        "known_hosts" => Ok("选择固定主机密钥文件"),
        "ssh" => Ok("选择 ssh 或 ssh.exe"),
        "asset" => Ok("选择已许可资产文件"),
        _ => Err("文件选择类型不受支持。".into()),
    }
}

#[tauri::command]
async fn choose_remote_file(kind: String) -> Result<Option<String>, String> {
    let title = dialog_title(&kind)?;
    #[cfg(any(target_os = "windows", target_os = "macos"))]
    {
        tauri::async_runtime::spawn_blocking(move || {
            let mut dialog = rfd::FileDialog::new().set_title(title);
            if kind == "config"
                || kind == "version_config"
                || kind == "release_manifest"
                || kind == "release_keys"
            {
                dialog = dialog.add_filter("连接配置", &["json"]);
            }
            match dialog.pick_file() {
                None => Ok(None),
                Some(path) if path.is_absolute() && path.is_file() => {
                    Ok(Some(path.to_string_lossy().into_owned()))
                }
                _ => Err("请选择本机普通文件。".into()),
            }
        })
        .await
        .map_err(|_| "文件选择未完成。".to_string())?
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        let _ = title;
        Err("此平台暂未提供原生文件选择，请填写绝对路径。".into())
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn file_dialog_does_not_accept_paths_or_commands_as_kind() {
        for value in ["../identity", "cmd.exe", "asset --run", "", "root"] {
            assert!(super::dialog_title(value).is_err());
        }
    }
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            bridge,
            remote_bridge,
            client_bridge,
            version_bridge,
            version_setup,
            choose_remote_file
        ])
        .run(tauri::generate_context!())
        .expect("CTFLab 桌面入口未启动");
}

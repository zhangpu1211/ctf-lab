//! 固定桥接进程的有界传输；超时只结束本次等待，不终止业务进程或重发请求。
use std::{
    io::{Read, Write},
    process::{Command, Stdio},
    sync::{
        atomic::{AtomicUsize, Ordering},
        mpsc, Arc,
    },
    thread,
    time::Duration,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Error {
    Busy,
    InputTooLarge,
    Spawn,
    Input,
    Output,
    OutputLimit,
    Timeout,
    Wait,
    Worker,
}

impl Error {
    pub fn message(self) -> &'static str {
        match self {
            Self::Busy => "待核验的本地请求已达上限；本次未启动新进程，请先核对已有请求。",
            Self::InputTooLarge => "请求超过容量，本次未启动桥接进程。",
            Self::Spawn => "本地运行时未就绪，请检查安装包清单。",
            Self::OutputLimit => "响应超过容量，原请求结果仍未确认；请读取状态，不要重复创建。",
            Self::Timeout => "等待已超时，原请求可能继续执行；请核对原操作状态，不要重复创建。",
            _ => "本地请求的结果未确认；后台不会被自动停止，请先读取原操作状态。",
        }
    }
}

struct Permit(Arc<AtomicUsize>);
impl Drop for Permit {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::AcqRel);
    }
}

pub struct Transport {
    active: Arc<AtomicUsize>,
    maximum: usize,
}

impl Transport {
    pub fn new(maximum: usize) -> Self {
        assert!(maximum > 0);
        Self {
            active: Arc::new(AtomicUsize::new(0)),
            maximum,
        }
    }

    pub fn execute(
        &self,
        mut command: Command,
        input: Vec<u8>,
        timeout: Duration,
        output_limit: usize,
    ) -> Result<Vec<u8>, Error> {
        if input.len() > 65536 {
            return Err(Error::InputTooLarge);
        }
        self.active
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |active| {
                (active < self.maximum).then_some(active + 1)
            })
            .map_err(|_| Error::Busy)?;
        let permit = Permit(Arc::clone(&self.active));
        let (sender, receiver) = mpsc::channel();
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        thread::Builder::new()
            .name("ctflab-bridge".into())
            .spawn(move || {
                let mut child = match command.spawn() {
                    Ok(child) => child,
                    Err(_) => {
                        let _ = sender.send(Err(Error::Spawn));
                        return;
                    }
                };
                let mut stdin = child.stdin.take().expect("固定桥接输入管道");
                let mut stdout = child.stdout.take().expect("固定桥接输出管道");
                let input_sender = sender.clone();
                let writer = thread::Builder::new()
                    .name("ctflab-bridge-input".into())
                    .spawn(move || {
                        stdin.write_all(&input).map_err(|_| {
                            let _ = input_sender.send(Err(Error::Input));
                            Error::Input
                        })
                    });
                let output_sender = sender.clone();
                let reader = thread::Builder::new()
                    .name("ctflab-bridge-output".into())
                    .spawn(move || {
                        let mut buffer = [0; 8192];
                        let mut kept = Vec::with_capacity(output_limit.min(8192));
                        let mut overflow = false;
                        loop {
                            let count = match stdout.read(&mut buffer) {
                                Ok(0) => break,
                                Ok(count) => count,
                                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => {
                                    continue;
                                }
                                Err(_) => {
                                    let _ = output_sender.send(Err(Error::Output));
                                    return Err(Error::Output);
                                }
                            };
                            if !overflow {
                                if count > output_limit.saturating_sub(kept.len()) {
                                    overflow = true;
                                    kept.clear();
                                    let _ = output_sender.send(Err(Error::OutputLimit));
                                } else {
                                    kept.extend_from_slice(&buffer[..count]);
                                }
                            }
                            // 越限后继续丢弃并排空，避免关闭管道使后台中途退出。
                        }
                        if overflow {
                            Err(Error::OutputLimit)
                        } else {
                            Ok(kept)
                        }
                    });
                if writer.is_err() || reader.is_err() {
                    let _ = sender.send(Err(Error::Worker));
                }
                // 只有本桥接进程退出且两条管道收口，才释放并发槽位。没有kill路径。
                let waited = child.wait();
                if waited.is_err() {
                    let _ = sender.send(Err(Error::Wait));
                }
                let written = writer
                    .map_err(|_| Error::Worker)
                    .and_then(|handle| handle.join().map_err(|_| Error::Worker))
                    .and_then(|value| value);
                let output = reader
                    .map_err(|_| Error::Worker)
                    .and_then(|handle| handle.join().map_err(|_| Error::Worker))
                    .and_then(|value| value);
                let result = written.and(output);
                if waited.is_err() {
                    // 退出未核对时保留槽位；不能因观察失败放入更多未决后台。
                    std::mem::forget(permit);
                } else {
                    drop(permit);
                }
                // 非零退出也可能携带契约错误JSON，交给原解析与业务契约处理。
                let _ = sender.send(result);
            })
            .map_err(|_| Error::Worker)?;
        receiver
            .recv_timeout(timeout)
            .map_err(|error| match error {
                mpsc::RecvTimeoutError::Timeout => Error::Timeout,
                mpsc::RecvTimeoutError::Disconnected => Error::Worker,
            })?
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{fs, path::PathBuf, time::Instant};
    static NEXT: AtomicUsize = AtomicUsize::new(0);

    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "ctflab-transport-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            let mut directory = fs::DirBuilder::new();
            #[cfg(unix)]
            {
                use std::os::unix::fs::DirBuilderExt;
                directory.mode(0o700);
            }
            directory.create(&root).unwrap();
            Self(root)
        }
        fn command(&self, mode: &str) -> Command {
            let mut command = Command::new(std::env::current_exe().unwrap());
            command.args(["--exact", "transport::tests::bridge_fixture", "--nocapture"]);
            command.env("CTFLAB_TRANSPORT_TEST_MODE", mode);
            command.env("CTFLAB_TRANSPORT_TEST_ROOT", &self.0);
            command
        }
        fn release(&self) {
            fs::write(self.0.join("release"), b"release").unwrap();
        }
        fn assert_finished(&self, transport: &Transport) {
            let deadline = Instant::now() + Duration::from_secs(5);
            while transport.active.load(Ordering::Acquire) != 0 && Instant::now() < deadline {
                thread::sleep(Duration::from_millis(5));
            }
            assert_eq!(transport.active.load(Ordering::Acquire), 0);
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::write(self.0.join("release"), b"release");
            if !thread::panicking() {
                let _ = fs::remove_dir_all(&self.0);
            }
        }
    }

    // 只编入测试二进制；不启动Python/QEMU/来宾，不接受生产入口的程序参数。
    #[test]
    fn bridge_fixture() {
        let Ok(mode) = std::env::var("CTFLAB_TRANSPORT_TEST_MODE") else {
            return;
        };
        let root = PathBuf::from(std::env::var_os("CTFLAB_TRANSPORT_TEST_ROOT").unwrap());
        if mode == "descendant" {
            Command::new(std::env::current_exe().unwrap())
                .args(["--exact", "transport::tests::bridge_fixture", "--nocapture"])
                .env("CTFLAB_TRANSPORT_TEST_MODE", "gate")
                .stdin(Stdio::null())
                .stdout(Stdio::inherit())
                .stderr(Stdio::null())
                .spawn()
                .unwrap();
            fs::write(root.join("root-exited"), b"root-exited").unwrap();
            std::process::exit(0);
        }
        if mode == "gate" {
            let deadline = Instant::now() + Duration::from_secs(4);
            while !root.join("release").exists() && Instant::now() < deadline {
                thread::sleep(Duration::from_millis(5));
            }
        }
        if mode == "slow" {
            thread::sleep(Duration::from_millis(200));
        }
        let mut input = Vec::new();
        std::io::stdin().read_to_end(&mut input).unwrap();
        if mode == "huge" {
            std::io::stdout().write_all(&vec![b'x'; 65536]).unwrap();
            std::io::stdout().flush().unwrap();
            thread::sleep(Duration::from_millis(100));
        } else if mode == "binary" {
            std::io::stdout().write_all(&[0xff, 0xfe]).unwrap();
        } else if mode == "nonzero" {
            std::io::stdout()
                .write_all(br#"{"state":"refused-or-unknown"}"#)
                .unwrap();
            std::io::stdout().flush().unwrap();
            fs::write(root.join("finished"), b"finished").unwrap();
            std::process::exit(2);
        } else {
            println!("stdin-bytes:{}", input.len());
        }
        fs::write(root.join("finished"), b"finished").unwrap();
    }

    #[test]
    fn bounded_full_input_and_output_are_reaped() {
        let fixture = Fixture::new();
        let transport = Transport::new(1);
        let output = transport
            .execute(
                fixture.command("normal"),
                vec![b'x'; 65536],
                Duration::from_secs(5),
                4 * 1024 * 1024,
            )
            .unwrap();
        assert!(String::from_utf8(output)
            .unwrap()
            .contains("stdin-bytes:65536"));
        fixture.assert_finished(&transport);
        assert!(fixture.0.join("finished").exists());
    }

    #[test]
    fn overflow_returns_unknown_but_does_not_close_the_writers_pipe() {
        let fixture = Fixture::new();
        let transport = Transport::new(1);
        assert_eq!(
            transport.execute(fixture.command("huge"), vec![], Duration::from_secs(5), 256),
            Err(Error::OutputLimit)
        );
        fixture.assert_finished(&transport);
        assert!(fixture.0.join("finished").exists());
    }

    #[test]
    fn timeout_including_blocked_input_does_not_kill_child() {
        let fixture = Fixture::new();
        let transport = Transport::new(1);
        let started = Instant::now();
        assert_eq!(
            transport.execute(
                fixture.command("slow"),
                vec![b'x'; 65536],
                Duration::from_millis(10),
                4096
            ),
            Err(Error::Timeout)
        );
        assert!(started.elapsed() < Duration::from_secs(2));
        fixture.assert_finished(&transport);
        assert!(fixture.0.join("finished").exists());
    }

    #[test]
    fn timed_out_child_retains_slot_until_terminal_and_busy_creates_nothing() {
        let fixture = Fixture::new();
        let transport = Transport::new(1);
        assert_eq!(
            transport.execute(
                fixture.command("gate"),
                vec![],
                Duration::from_millis(10),
                4096
            ),
            Err(Error::Timeout)
        );
        assert_eq!(
            transport.execute(
                fixture.command("normal"),
                vec![],
                Duration::from_secs(5),
                4096
            ),
            Err(Error::Busy)
        );
        assert!(!fixture.0.join("finished").exists());
        fixture.release();
        fixture.assert_finished(&transport);
        assert!(fixture.0.join("finished").exists());
        assert!(transport
            .execute(
                fixture.command("normal"),
                vec![],
                Duration::from_secs(5),
                4096
            )
            .is_ok());
        fixture.assert_finished(&transport);
    }

    #[test]
    fn spawn_failure_releases_slot_without_process_cleanup_commands() {
        let fixture = Fixture::new();
        let transport = Transport::new(1);
        assert_eq!(
            transport.execute(
                Command::new(fixture.0.join("absent")),
                vec![],
                Duration::from_secs(5),
                4096
            ),
            Err(Error::Spawn)
        );
        fixture.assert_finished(&transport);
        assert!(!fixture.0.join("finished").exists());
    }

    #[test]
    fn root_exit_does_not_release_slot_while_descendant_holds_stdout() {
        let fixture = Fixture::new();
        let transport = Transport::new(1);
        assert_eq!(
            transport.execute(
                fixture.command("descendant"),
                vec![],
                Duration::from_millis(10),
                4096
            ),
            Err(Error::Timeout)
        );
        let deadline = Instant::now() + Duration::from_secs(3);
        while !fixture.0.join("root-exited").exists() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(5));
        }
        assert!(fixture.0.join("root-exited").exists());
        assert_eq!(
            transport.execute(
                fixture.command("normal"),
                vec![],
                Duration::from_secs(5),
                4096
            ),
            Err(Error::Busy)
        );
        fixture.release();
        fixture.assert_finished(&transport);
        assert!(fixture.0.join("finished").exists());
    }

    #[test]
    fn oversize_input_is_refused_before_start() {
        let fixture = Fixture::new();
        let transport = Transport::new(1);
        assert_eq!(
            transport.execute(
                fixture.command("normal"),
                vec![0; 65537],
                Duration::from_secs(5),
                4096
            ),
            Err(Error::InputTooLarge)
        );
        assert_eq!(transport.active.load(Ordering::Acquire), 0);
        assert!(!fixture.0.join("finished").exists());
    }

    #[test]
    fn nonzero_exit_keeps_contract_error_output() {
        let fixture = Fixture::new();
        let transport = Transport::new(1);
        let output = transport
            .execute(
                fixture.command("nonzero"),
                vec![],
                Duration::from_secs(5),
                4096,
            )
            .unwrap();
        assert!(String::from_utf8(output)
            .unwrap()
            .contains("refused-or-unknown"));
        fixture.assert_finished(&transport);
    }

    #[test]
    fn invalid_utf8_stays_raw_for_original_json_parser_to_refuse() {
        let fixture = Fixture::new();
        let transport = Transport::new(1);
        let output = transport
            .execute(
                fixture.command("binary"),
                vec![],
                Duration::from_secs(5),
                4096,
            )
            .unwrap();
        assert!(String::from_utf8(output).is_err());
        fixture.assert_finished(&transport);
    }
}

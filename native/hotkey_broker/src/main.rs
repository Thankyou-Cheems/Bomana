#![cfg_attr(windows, windows_subsystem = "windows")]

#[cfg(windows)]
mod broker {
    use std::env;
    use std::ffi::c_void;
    use std::mem::zeroed;
    use std::ptr::null_mut;
    use std::thread;
    use std::time::Duration;

    type Bool = i32;
    type Dword = u32;
    type Handle = *mut c_void;
    type Hwnd = *mut c_void;

    const FALSE: Bool = 0;
    const GENERIC_WRITE: Dword = 0x4000_0000;
    const OPEN_EXISTING: Dword = 3;
    const ERROR_PIPE_BUSY: Dword = 231;
    const SYNCHRONIZE: Dword = 0x0010_0000;
    const PROCESS_QUERY_LIMITED_INFORMATION: Dword = 0x1000;
    const MOD_NOREPEAT: Dword = 0x4000;
    const WM_HOTKEY: Dword = 0x0312;
    const WM_QUIT: Dword = 0x0012;
    const PM_REMOVE: Dword = 0x0001;
    const QS_ALLINPUT: Dword = 0x04ff;
    const INFINITE: Dword = 0xffff_ffff;
    const WAIT_OBJECT_0: Dword = 0;
    const WAIT_FAILED: Dword = 0xffff_ffff;
    const INVALID_HANDLE_VALUE: Handle = -1_isize as Handle;
    const FRAME_MAGIC: [u8; 4] = *b"BHK1";
    const FRAME_READY: u8 = 1;
    const FRAME_ACTION: u8 = 2;

    #[repr(C)]
    #[derive(Clone, Copy)]
    struct Point {
        x: i32,
        y: i32,
    }

    #[repr(C)]
    #[derive(Clone, Copy)]
    struct Msg {
        hwnd: Hwnd,
        message: Dword,
        w_param: usize,
        l_param: isize,
        time: Dword,
        point: Point,
        private: Dword,
    }

    #[link(name = "user32")]
    unsafe extern "system" {
        fn RegisterHotKey(hwnd: Hwnd, id: i32, modifiers: Dword, virtual_key: Dword) -> Bool;
        fn UnregisterHotKey(hwnd: Hwnd, id: i32) -> Bool;
        fn MsgWaitForMultipleObjects(
            count: Dword,
            handles: *const Handle,
            wait_all: Bool,
            milliseconds: Dword,
            wake_mask: Dword,
        ) -> Dword;
        fn PeekMessageW(
            message: *mut Msg,
            hwnd: Hwnd,
            minimum: Dword,
            maximum: Dword,
            remove: Dword,
        ) -> Bool;
        fn TranslateMessage(message: *const Msg) -> Bool;
        fn DispatchMessageW(message: *const Msg) -> isize;
    }

    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn CreateFileW(
            file_name: *const u16,
            desired_access: Dword,
            share_mode: Dword,
            security_attributes: *mut c_void,
            creation_disposition: Dword,
            flags_and_attributes: Dword,
            template_file: Handle,
        ) -> Handle;
        fn WaitNamedPipeW(name: *const u16, timeout: Dword) -> Bool;
        fn WriteFile(
            file: Handle,
            buffer: *const c_void,
            bytes_to_write: Dword,
            bytes_written: *mut Dword,
            overlapped: *mut c_void,
        ) -> Bool;
        fn GetLastError() -> Dword;
        fn GetNamedPipeServerProcessId(pipe: Handle, server_process_id: *mut Dword) -> Bool;
        fn OpenEventW(desired_access: Dword, inherit_handle: Bool, name: *const u16) -> Handle;
        fn OpenProcess(desired_access: Dword, inherit_handle: Bool, process_id: Dword) -> Handle;
        fn ProcessIdToSessionId(process_id: Dword, session_id: *mut Dword) -> Bool;
        fn GetCurrentProcessId() -> Dword;
        fn CloseHandle(handle: Handle) -> Bool;
    }

    #[derive(Clone, Copy, Debug, Eq, PartialEq)]
    enum Action {
        Reset = 1,
        Lock = 2,
        Corner = 3,
        Beep = 4,
        Zones = 5,
        BombTarget = 6,
    }

    impl Action {
        fn parse(value: &str) -> Option<Self> {
            match value {
                "reset" => Some(Self::Reset),
                "lock" => Some(Self::Lock),
                "corner" => Some(Self::Corner),
                "beep" => Some(Self::Beep),
                "zones" => Some(Self::Zones),
                "bomb_target" => Some(Self::BombTarget),
                _ => None,
            }
        }

        fn hotkey_id(self) -> i32 {
            7006 + self as i32
        }

        fn failure_bit(self) -> u16 {
            1_u16 << ((self as u16) - 1)
        }
    }

    #[derive(Clone, Copy, Debug, Eq, PartialEq)]
    struct Binding {
        action: Action,
        virtual_key: Dword,
    }

    #[derive(Debug, Eq, PartialEq)]
    struct Session {
        token: String,
        app_process_id: Dword,
        bindings: Vec<Binding>,
    }

    impl Session {
        fn pipe_name(&self) -> String {
            format!(r"\\.\pipe\Bomana.HotkeyBroker.{}", self.token)
        }

        fn stop_event_name(&self) -> String {
            format!(r"Local\Bomana.HotkeyBroker.Stop.{}", self.token)
        }
    }

    struct OwnedHandle(Handle);

    impl OwnedHandle {
        fn new(handle: Handle) -> Option<Self> {
            if handle.is_null() || handle == INVALID_HANDLE_VALUE {
                None
            } else {
                Some(Self(handle))
            }
        }

        fn raw(&self) -> Handle {
            self.0
        }
    }

    impl Drop for OwnedHandle {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }

    struct RegisteredHotkeys(Vec<i32>);

    impl Drop for RegisteredHotkeys {
        fn drop(&mut self) {
            for id in self.0.drain(..) {
                unsafe {
                    UnregisterHotKey(null_mut(), id);
                }
            }
        }
    }

    fn wide(value: &str) -> Vec<u16> {
        value.encode_utf16().chain([0]).collect()
    }

    fn parse_virtual_key(value: &str) -> Option<Dword> {
        let number = value.strip_prefix('F')?.parse::<u32>().ok()?;
        if (1..=12).contains(&number) {
            Some(0x70 + number - 1)
        } else {
            None
        }
    }

    fn parse_binding(value: &str) -> Result<Binding, String> {
        let (action_name, key_name) = value
            .split_once('=')
            .ok_or_else(|| "binding must be ACTION=F1..F12".to_owned())?;
        let action = Action::parse(action_name).ok_or_else(|| "unsupported action".to_owned())?;
        let virtual_key =
            parse_virtual_key(key_name).ok_or_else(|| "unsupported function key".to_owned())?;
        Ok(Binding {
            action,
            virtual_key,
        })
    }

    fn parse_session_token(token: &str) -> Result<Dword, String> {
        let (pid_text, nonce) = token
            .split_once('-')
            .ok_or_else(|| "invalid session token".to_owned())?;
        if nonce.len() != 32 || !nonce.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err("invalid session nonce".to_owned());
        }
        let process_id = pid_text
            .parse::<Dword>()
            .map_err(|_| "invalid app process id".to_owned())?;
        if process_id == 0 {
            return Err("invalid app process id".to_owned());
        }
        Ok(process_id)
    }

    fn parse_args(args: impl IntoIterator<Item = String>) -> Result<Session, String> {
        let mut args = args.into_iter();
        let mut token: Option<String> = None;
        let mut bindings = Vec::new();

        while let Some(flag) = args.next() {
            match flag.as_str() {
                "--session" if token.is_none() => {
                    token = Some(
                        args.next()
                            .ok_or_else(|| "--session requires one token".to_owned())?,
                    );
                }
                "--binding" => {
                    let value = args
                        .next()
                        .ok_or_else(|| "--binding requires one value".to_owned())?;
                    bindings.push(parse_binding(&value)?);
                }
                _ => return Err("unsupported broker argument".to_owned()),
            }
        }

        let token = token.ok_or_else(|| "missing --session".to_owned())?;
        let app_process_id = parse_session_token(&token)?;
        if !(4..=6).contains(&bindings.len()) {
            return Err("broker requires four to six fixed actions".to_owned());
        }

        for required in [Action::Reset, Action::Lock, Action::Corner, Action::Beep] {
            if !bindings.iter().any(|binding| binding.action == required) {
                return Err("missing required fixed action".to_owned());
            }
        }
        for (index, binding) in bindings.iter().enumerate() {
            if bindings[..index].iter().any(|prior| {
                prior.action == binding.action || prior.virtual_key == binding.virtual_key
            }) {
                return Err("duplicate action or function key".to_owned());
            }
        }
        bindings.sort_by_key(|binding| binding.action as u8);

        Ok(Session {
            token,
            app_process_id,
            bindings,
        })
    }

    fn frame(kind: u8, code: u8, detail: u16) -> [u8; 8] {
        let detail = detail.to_le_bytes();
        [
            FRAME_MAGIC[0],
            FRAME_MAGIC[1],
            FRAME_MAGIC[2],
            FRAME_MAGIC[3],
            kind,
            code,
            detail[0],
            detail[1],
        ]
    }

    fn write_frame(pipe: Handle, payload: [u8; 8]) -> bool {
        let mut written = 0;
        let ok = unsafe {
            WriteFile(
                pipe,
                payload.as_ptr().cast(),
                payload.len() as Dword,
                &mut written,
                null_mut(),
            )
        };
        ok != FALSE && written == payload.len() as Dword
    }

    fn connect_pipe(name: &str) -> Option<OwnedHandle> {
        let wide_name = wide(name);
        for _ in 0..6 {
            let handle = unsafe {
                CreateFileW(
                    wide_name.as_ptr(),
                    GENERIC_WRITE,
                    0,
                    null_mut(),
                    OPEN_EXISTING,
                    0,
                    null_mut(),
                )
            };
            if let Some(handle) = OwnedHandle::new(handle) {
                return Some(handle);
            }
            let error = unsafe { GetLastError() };
            if error == ERROR_PIPE_BUSY {
                unsafe {
                    WaitNamedPipeW(wide_name.as_ptr(), 1000);
                }
            } else {
                thread::sleep(Duration::from_millis(100));
            }
        }
        None
    }

    fn same_windows_session(app_process_id: Dword) -> bool {
        let mut app_session = 0;
        let mut broker_session = 0;
        let broker_process_id = unsafe { GetCurrentProcessId() };
        unsafe {
            ProcessIdToSessionId(app_process_id, &mut app_session) != FALSE
                && ProcessIdToSessionId(broker_process_id, &mut broker_session) != FALSE
                && app_session == broker_session
        }
    }

    fn run_session(session: Session) -> i32 {
        let Some(pipe) = connect_pipe(&session.pipe_name()) else {
            return 20;
        };

        let mut server_process_id = 0;
        if unsafe { GetNamedPipeServerProcessId(pipe.raw(), &mut server_process_id) } == FALSE
            || server_process_id != session.app_process_id
            || !same_windows_session(session.app_process_id)
        {
            return 21;
        }

        let Some(app_process) = OwnedHandle::new(unsafe {
            OpenProcess(
                SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
                FALSE,
                session.app_process_id,
            )
        }) else {
            return 22;
        };
        let event_name = wide(&session.stop_event_name());
        let Some(stop_event) =
            OwnedHandle::new(unsafe { OpenEventW(SYNCHRONIZE, FALSE, event_name.as_ptr()) })
        else {
            return 23;
        };

        let mut registered = RegisteredHotkeys(Vec::new());
        let mut failure_mask = 0_u16;
        for binding in &session.bindings {
            let id = binding.action.hotkey_id();
            let ok = unsafe { RegisterHotKey(null_mut(), id, MOD_NOREPEAT, binding.virtual_key) }
                != FALSE;
            if ok {
                registered.0.push(id);
            } else {
                failure_mask |= binding.action.failure_bit();
            }
        }

        if !write_frame(
            pipe.raw(),
            frame(FRAME_READY, registered.0.len() as u8, failure_mask),
        ) {
            return 24;
        }

        let handles = [app_process.raw(), stop_event.raw()];
        let mut running = true;
        while running {
            let wait_result = unsafe {
                MsgWaitForMultipleObjects(
                    handles.len() as Dword,
                    handles.as_ptr(),
                    FALSE,
                    INFINITE,
                    QS_ALLINPUT,
                )
            };
            if wait_result == WAIT_OBJECT_0 || wait_result == WAIT_OBJECT_0 + 1 {
                break;
            }
            if wait_result == WAIT_FAILED {
                return 25;
            }
            if wait_result != WAIT_OBJECT_0 + handles.len() as Dword {
                continue;
            }

            let mut message: Msg = unsafe { zeroed() };
            while unsafe { PeekMessageW(&mut message, null_mut(), 0, 0, PM_REMOVE) } != FALSE {
                if message.message == WM_QUIT {
                    running = false;
                    break;
                }
                if message.message == WM_HOTKEY {
                    let id = message.w_param as i32;
                    if let Some(binding) = session
                        .bindings
                        .iter()
                        .find(|binding| binding.action.hotkey_id() == id)
                        && !write_frame(pipe.raw(), frame(FRAME_ACTION, binding.action as u8, 0))
                    {
                        running = false;
                        break;
                    }
                    continue;
                }
                unsafe {
                    TranslateMessage(&message);
                    DispatchMessageW(&message);
                }
            }
        }
        0
    }

    pub fn run() -> i32 {
        match parse_args(env::args().skip(1)) {
            Ok(session) => run_session(session),
            Err(_) => 2,
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        fn valid_args() -> Vec<String> {
            [
                "--session",
                "1234-0123456789abcdef0123456789abcdef",
                "--binding",
                "reset=F7",
                "--binding",
                "lock=F8",
                "--binding",
                "corner=F9",
                "--binding",
                "beep=F10",
                "--binding",
                "zones=F11",
                "--binding",
                "bomb_target=F6",
            ]
            .into_iter()
            .map(str::to_owned)
            .collect()
        }

        #[test]
        fn accepts_only_fixed_actions_and_function_keys() {
            let parsed = parse_args(valid_args()).expect("valid broker args");
            assert_eq!(parsed.app_process_id, 1234);
            assert_eq!(parsed.bindings.len(), 6);
            assert_eq!(parsed.bindings[0].action, Action::Reset);
            assert_eq!(parsed.bindings[5].virtual_key, 0x75);
        }

        #[test]
        fn rejects_unknown_arguments_and_actions() {
            let mut unknown_flag = valid_args();
            unknown_flag.extend(["--command".to_owned(), "calc.exe".to_owned()]);
            assert!(parse_args(unknown_flag).is_err());

            let mut unknown_action = valid_args();
            let index = unknown_action
                .iter()
                .position(|item| item == "reset=F7")
                .unwrap();
            unknown_action[index] = "shell=F7".to_owned();
            assert!(parse_args(unknown_action).is_err());
        }

        #[test]
        fn rejects_duplicate_keys_and_bad_session_tokens() {
            let mut duplicate = valid_args();
            let index = duplicate.iter().position(|item| item == "lock=F8").unwrap();
            duplicate[index] = "lock=F7".to_owned();
            assert!(parse_args(duplicate).is_err());

            let mut bad_session = valid_args();
            bad_session[1] = "1234-short".to_owned();
            assert!(parse_args(bad_session).is_err());
        }

        #[test]
        fn frames_are_fixed_eight_byte_messages() {
            assert_eq!(frame(FRAME_READY, 5, 0x0010), *b"BHK1\x01\x05\x10\x00");
            assert_eq!(
                frame(FRAME_ACTION, Action::Lock as u8, 0),
                *b"BHK1\x02\x02\x00\x00"
            );
        }
    }
}

#[cfg(windows)]
fn main() {
    std::process::exit(broker::run());
}

#[cfg(not(windows))]
fn main() {
    eprintln!("BomanaHotkeyBroker is Windows-only");
    std::process::exit(1);
}

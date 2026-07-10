#![cfg_attr(windows, windows_subsystem = "windows")]

#[cfg(windows)]
mod setup {
    use std::env;
    use std::ffi::c_void;
    use std::fs::{self, File};
    use std::io::Write;
    use std::path::{Path, PathBuf};
    use std::ptr::null_mut;

    type Bool = i32;
    type Dword = u32;
    type Handle = *mut c_void;
    type Hwnd = *mut c_void;

    const FALSE: Bool = 0;
    const TOKEN_QUERY: Dword = 0x0008;
    const TOKEN_INFORMATION_CLASS_ELEVATION: i32 = 20;
    const SEE_MASK_NOCLOSEPROCESS: Dword = 0x0000_0040;
    const SW_SHOWNORMAL: i32 = 1;
    const MOVEFILE_REPLACE_EXISTING: Dword = 0x0000_0001;
    const MOVEFILE_WRITE_THROUGH: Dword = 0x0000_0008;
    const SE_FILE_OBJECT: Dword = 1;
    const DACL_SECURITY_INFORMATION: Dword = 0x0000_0004;
    const PROTECTED_DACL_SECURITY_INFORMATION: Dword = 0x8000_0000;
    const MB_ICONERROR: Dword = 0x0000_0010;
    const MB_ICONINFORMATION: Dword = 0x0000_0040;
    const BROKER_BYTES: &[u8] = include_bytes!(env!("BOMANA_BROKER_PAYLOAD"));

    #[repr(C)]
    struct Guid {
        data1: Dword,
        data2: u16,
        data3: u16,
        data4: [u8; 8],
    }

    #[repr(C)]
    struct TokenElevation {
        token_is_elevated: Dword,
    }

    #[repr(C)]
    struct ShellExecuteInfoW {
        cb_size: Dword,
        mask: Dword,
        hwnd: Hwnd,
        verb: *const u16,
        file: *const u16,
        parameters: *const u16,
        directory: *const u16,
        show: i32,
        instance: Handle,
        id_list: *mut c_void,
        class: *const u16,
        key_class: Handle,
        hot_key: Dword,
        icon_or_monitor: Handle,
        process: Handle,
    }

    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn GetCurrentProcess() -> Handle;
        fn CloseHandle(handle: Handle) -> Bool;
        fn LocalFree(memory: Handle) -> Handle;
        fn MoveFileExW(existing: *const u16, new: *const u16, flags: Dword) -> Bool;
    }

    #[link(name = "ole32")]
    unsafe extern "system" {
        fn CoTaskMemFree(memory: *mut c_void);
    }

    #[link(name = "advapi32")]
    unsafe extern "system" {
        fn OpenProcessToken(process: Handle, access: Dword, token: *mut Handle) -> Bool;
        fn GetTokenInformation(
            token: Handle,
            information_class: i32,
            information: *mut c_void,
            information_size: Dword,
            returned_size: *mut Dword,
        ) -> Bool;
        fn ConvertStringSecurityDescriptorToSecurityDescriptorW(
            text: *const u16,
            revision: Dword,
            descriptor: *mut *mut c_void,
            descriptor_size: *mut Dword,
        ) -> Bool;
        fn GetSecurityDescriptorDacl(
            descriptor: *mut c_void,
            present: *mut Bool,
            dacl: *mut *mut c_void,
            defaulted: *mut Bool,
        ) -> Bool;
        fn SetNamedSecurityInfoW(
            object_name: *mut u16,
            object_type: Dword,
            security_info: Dword,
            owner: *mut c_void,
            group: *mut c_void,
            dacl: *mut c_void,
            sacl: *mut c_void,
        ) -> Dword;
    }

    #[link(name = "shell32")]
    unsafe extern "system" {
        fn SHGetKnownFolderPath(
            folder_id: *const Guid,
            flags: Dword,
            token: Handle,
            path: *mut *mut u16,
        ) -> i32;
        fn ShellExecuteExW(info: *mut ShellExecuteInfoW) -> Bool;
    }

    #[link(name = "user32")]
    unsafe extern "system" {
        fn MessageBoxW(hwnd: Hwnd, text: *const u16, caption: *const u16, kind: Dword) -> i32;
    }

    fn wide(value: &str) -> Vec<u16> {
        value.encode_utf16().chain([0]).collect()
    }

    fn show_message(text: &str, error: bool) {
        let text = wide(text);
        let caption = wide("Bomana 游戏内热键组件");
        unsafe {
            MessageBoxW(
                null_mut(),
                text.as_ptr(),
                caption.as_ptr(),
                if error {
                    MB_ICONERROR
                } else {
                    MB_ICONINFORMATION
                },
            );
        }
    }

    fn is_elevated() -> bool {
        let mut token: Handle = null_mut();
        let opened = unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) };
        if opened == FALSE || token.is_null() {
            return false;
        }
        let mut elevation = TokenElevation {
            token_is_elevated: 0,
        };
        let mut returned = 0;
        let ok = unsafe {
            GetTokenInformation(
                token,
                TOKEN_INFORMATION_CLASS_ELEVATION,
                (&mut elevation as *mut TokenElevation).cast(),
                size_of::<TokenElevation>() as Dword,
                &mut returned,
            )
        };
        unsafe {
            CloseHandle(token);
        }
        ok != FALSE && elevation.token_is_elevated != 0
    }

    fn program_files() -> Result<PathBuf, String> {
        let folder_id = Guid {
            data1: 0x905E63B6,
            data2: 0xC1BF,
            data3: 0x494E,
            data4: [0xB2, 0x9C, 0x65, 0xB7, 0x32, 0xD3, 0xD2, 0x1A],
        };
        let mut pointer: *mut u16 = null_mut();
        let status = unsafe { SHGetKnownFolderPath(&folder_id, 0, null_mut(), &mut pointer) };
        if status != 0 || pointer.is_null() {
            return Err("无法定位 Program Files。".to_owned());
        }
        let mut length = 0;
        unsafe {
            while *pointer.add(length) != 0 {
                length += 1;
            }
        }
        let value =
            unsafe { String::from_utf16_lossy(std::slice::from_raw_parts(pointer, length)) };
        unsafe {
            CoTaskMemFree(pointer.cast());
        }
        Ok(PathBuf::from(value))
    }

    fn install() -> Result<PathBuf, String> {
        if BROKER_BYTES.len() < 1024 {
            return Err("内置热键组件无效。".to_owned());
        }
        let directory = program_files()?.join("Bomana").join("HotkeyBroker");
        fs::create_dir_all(&directory).map_err(|error| format!("无法创建安装目录：{error}"))?;
        apply_protected_acl(&directory)?;
        let target = directory.join("BomanaHotkeyBroker.exe");
        let staged = directory.join("BomanaHotkeyBroker.exe.new");
        let mut file = File::create(&staged).map_err(|error| format!("无法暂存组件：{error}"))?;
        file.write_all(BROKER_BYTES)
            .and_then(|_| file.sync_all())
            .map_err(|error| format!("无法写入组件：{error}"))?;
        drop(file);

        let staged_wide = wide_path(&staged);
        let target_wide = wide_path(&target);
        let moved = unsafe {
            MoveFileExW(
                staged_wide.as_ptr(),
                target_wide.as_ptr(),
                MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
            )
        };
        if moved == FALSE {
            let _ = fs::remove_file(&staged);
            return Err("无法替换热键组件；请先退出正在运行的 Bomana。".to_owned());
        }
        apply_protected_acl(&target)?;
        Ok(target)
    }

    fn wide_path(path: &Path) -> Vec<u16> {
        wide(&path.to_string_lossy())
    }

    fn apply_protected_acl(path: &Path) -> Result<(), String> {
        let sddl = wide("D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;BU)");
        let mut descriptor: *mut c_void = null_mut();
        let converted = unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl.as_ptr(),
                1,
                &mut descriptor,
                null_mut(),
            )
        };
        if converted == FALSE || descriptor.is_null() {
            return Err("无法创建热键组件安全描述符。".to_owned());
        }

        let mut present = FALSE;
        let mut defaulted = FALSE;
        let mut dacl: *mut c_void = null_mut();
        let extracted = unsafe {
            GetSecurityDescriptorDacl(descriptor, &mut present, &mut dacl, &mut defaulted)
        };
        if extracted == FALSE || present == FALSE || dacl.is_null() {
            unsafe {
                LocalFree(descriptor);
            }
            return Err("无法读取热键组件安全描述符。".to_owned());
        }

        let mut path_wide = wide_path(path);
        let status = unsafe {
            SetNamedSecurityInfoW(
                path_wide.as_mut_ptr(),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                null_mut(),
                null_mut(),
                dacl,
                null_mut(),
            )
        };
        unsafe {
            LocalFree(descriptor);
        }
        if status != 0 {
            return Err(format!("无法保护热键组件路径（Windows 错误 {status}）。"));
        }
        Ok(())
    }

    fn request_elevation() -> Result<(), String> {
        let executable =
            env::current_exe().map_err(|error| format!("无法定位安装程序：{error}"))?;
        let executable_wide = wide_path(&executable);
        let verb = wide("runas");
        let parameters = wide("--elevated-install");
        let directory = wide_path(executable.parent().unwrap_or_else(|| Path::new(".")));
        let mut info: ShellExecuteInfoW = unsafe { std::mem::zeroed() };
        info.cb_size = size_of::<ShellExecuteInfoW>() as Dword;
        info.mask = SEE_MASK_NOCLOSEPROCESS;
        info.verb = verb.as_ptr();
        info.file = executable_wide.as_ptr();
        info.parameters = parameters.as_ptr();
        info.directory = directory.as_ptr();
        info.show = SW_SHOWNORMAL;
        if unsafe { ShellExecuteExW(&mut info) } == FALSE {
            return Err("未获得管理员权限，热键组件没有安装。".to_owned());
        }
        if !info.process.is_null() {
            unsafe {
                CloseHandle(info.process);
            }
        }
        Ok(())
    }

    pub fn run() -> i32 {
        let arguments: Vec<String> = env::args().skip(1).collect();
        if arguments.is_empty() {
            return match request_elevation() {
                Ok(()) => 0,
                Err(message) => {
                    show_message(&message, true);
                    2
                }
            };
        }
        if arguments != ["--elevated-install"] || !is_elevated() {
            show_message("安装请求无效或未获得管理员权限。", true);
            return 3;
        }
        match install() {
            Ok(path) => {
                show_message(
                    &format!(
                        "游戏内热键组件已安全安装到：\n{}\n\n请返回 Bomana，点击“启用游戏内热键”。",
                        path.display()
                    ),
                    false,
                );
                0
            }
            Err(message) => {
                show_message(&message, true);
                4
            }
        }
    }
}

#[cfg(windows)]
fn main() {
    std::process::exit(setup::run());
}

#[cfg(not(windows))]
fn main() {
    eprintln!("BomanaHotkeyBrokerSetup is Windows-only");
    std::process::exit(1);
}

/**
 * 全局快捷键 Super+L（PRD 5.6）：通过自定义快捷键绑定唤起 UI。
 *
 * GNOME 46 扩展不再允许直接调用 Main.wm.addKeybinding 之外的私有 API；
 * 本扩展使用 org.gnome.settings-daemon.plugins.media-keys 自定义快捷键方案：
 * 扩展安装时（deb postinst）写入 custom0 绑定，这里只负责清理。
 */

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

const SHORTCUT_NAME = 'lingos-assistant-toggle';

/**
 * 尝试注册会话内快捷键（若被系统设置占用则静默降级——扩展是增强不是依赖，PRD 14.3 L4）。
 */
export function bindShortcut(extension, callback) {
    try {
        Main.wm.addKeybinding(
            SHORTCUT_NAME,
            extension.getSettings(),
            Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
            callback);
    } catch (e) {
        // 快捷键注册失败不影响托盘与通知路由
        log(`[lingos] shortcut bind failed: ${e}`);
    }
}

export function unbindShortcut(_extension) {
    try {
        Main.wm.removeKeybinding(SHORTCUT_NAME);
    } catch (e) {
        // 忽略
    }
}

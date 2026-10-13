/**
 * LingOS Assistant —— GNOME Shell 扩展（PRD 5.6）
 *
 * - 全局快捷键 Super+L 唤起助手面板（可在系统设置-键盘改绑）
 * - 托盘图标状态：就绪=品牌色圆点 / 熔断降级=灰色 / 无 Key=黄色感叹号
 * - 菜单：打开助手 / 打开设置 / 暂停工具能力 / 查看审计日志
 *
 * GNOME 46 只支持 ESM（PRD 11.2）。
 */

import St from 'gi://St';
import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {AssistantIndicator} from './tray.js';
import {bindShortcut, unbindShortcut} from './shortcut.js';

const RUNTIME_DIR = `${GLib.get_user_runtime_dir()}/lingos`;

export default class LingOSAssistantExtension extends Extension {
    enable() {
        this._settings = this.getSettings();
        this._readPortToken();

        // 托盘状态图标
        this._indicator = new AssistantIndicator();
        Main.panel.addToStatusArea('lingos-assistant', this._indicator);

        // 菜单项
        this._indicator.menu.addAction(_('打开助手'), () => this._launchUI());
        this._indicator.menu.addAction(_('打开设置'), () => this._launchUI(['--settings']));
        this._itemTools = new PopupMenu.PopupSwitchMenuItem(_('工具能力'), true);
        this._itemTools.connect('toggled', (item, state) => this._toggleTools(state));
        this._indicator.menu.addMenuItem(this._itemTools);
        this._indicator.menu.addAction(_('审计日志'), () => this._launchUI(['--audit']));

        // 全局快捷键 Super+L
        bindShortcut(this, () => this._launchUI(['--quick']));

        // 健康轮询：托盘状态刷新（10s，PRD 5.6 状态色）
        this._pollSource = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 10, () => {
            this._pollHealth();
            return GLib.SOURCE_CONTINUE;
        });
        this._pollHealth();
    }

    disable() {
        if (this._pollSource) {
            GLib.source_remove(this._pollSource);
            this._pollSource = null;
        }
        unbindShortcut(this);
        this._indicator?.destroy();
        this._indicator = null;
        this._itemTools = null;
        this._settings = null;
    }

    _readPortToken() {
        try {
            this._port = GLib.file_get_contents(`${RUNTIME_DIR}/port`)[1].toString().trim();
            this._token = GLib.file_get_contents(`${RUNTIME_DIR}/assistant.token`)[1].toString().trim();
        } catch (e) {
            this._port = null;
            this._token = null;
        }
    }

    _launchUI(args = []) {
        // 拉起 GTK UI（应用网格同款入口）
        try {
            const app = Gio.AppInfo.create_from_commandline(
                'lingos-assistant-ui ' + args.join(' '),
                'LingOS 助手',
                Gio.AppInfoCreateFlags.NONE);
            app.launch([], null);
        } catch (e) {
            Main.notifyError(_('无法启动 LingOS 助手'), String(e));
        }
    }

    _toggleTools(state) {
        // 快速开关 tools_enabled（PRD 5.6），同时写 dconf 特性开关
        this._settings.set_boolean('enable-tools', state);
        if (this._port && this._token) {
            const cmd = `curl -s -X PUT -H "Authorization: Bearer ${this._token}" ` +
                `-H "Content-Type: application/json" ` +
                `-d '{"tools_enabled": ${state}}' ` +
                `http://127.0.0.1:${this._port}/api/v1/settings`;
            GLib.spawn_command_line_async(cmd);
        }
    }

    _pollHealth() {
        this._readPortToken();
        if (!this._port || !this._token) {
            this._indicator?.setState('no-service');
            return;
        }
        try {
            const [ok, out] = GLib.spawn_command_line_sync(
                `curl -s -H "Authorization: Bearer ${this._token}" ` +
                `http://127.0.0.1:${this._port}/api/v1/healthz`);
            if (!ok) {
                this._indicator?.setState('degraded');
                return;
            }
            const health = JSON.parse(new TextDecoder().decode(out));
            if (!health.has_key)
                this._indicator?.setState('no-key');
            else if (health.circuit?.state === 'open')
                this._indicator?.setState('degraded');
            else
                this._indicator?.setState('ready');
            this._itemTools?.setToggleState(!!health.tools_enabled);
        } catch (e) {
            this._indicator?.setState('degraded');
        }
    }
}

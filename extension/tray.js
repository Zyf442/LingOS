/**
 * 托盘状态图标（PRD 5.6）：
 * - ready: 品牌色圆点（#4C6EF5）
 * - degraded（熔断降级）: 灰色
 * - no-key: 黄色感叹号
 * - no-service: 红色
 */

import St from 'gi://St';
import GObject from 'gi://GObject';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';

const STATES = {
    'ready': {icon: 'lingos-ready-symbolic', style: 'color: #4C6EF5;'},
    'degraded': {icon: 'lingos-degraded-symbolic', style: 'color: gray;'},
    'no-key': {icon: 'dialog-warning-symbolic', style: 'color: yellow;'},
    'no-service': {icon: 'dialog-error-symbolic', style: 'color: red;'},
};

export const AssistantIndicator = GObject.registerClass(
    class AssistantIndicator extends PanelMenu.Button {
        _init() {
            super._init(0.0, 'LingOS Assistant', true);
            this._icon = new St.Icon({
                icon_name: 'lingos-ready-symbolic',
                style_class: 'system-status-icon',
            });
            this.add_child(this._icon);
            this.setState('no-service');
        }

        setState(state) {
            const conf = STATES[state] ?? STATES['degraded'];
            this._icon.icon_name = conf.icon;
            this._icon.set_style(conf.style);
        }
    });

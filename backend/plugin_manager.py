"""
Plugin Manager - メタデータ付きイベントファンアウト配信システム

外部プログラムがMeeting Assistantのイベントを購読・処理できるプラグインシステム。
4つの通知プロトコルをサポート: WebSocket, Shell pipe, HTTP webhook, プロセス起動
"""

import asyncio
import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any, Set

logger = logging.getLogger("PluginManager")

# イベント種別
PLUGIN_EVENTS = [
    "transcription",       # 文字起こしテキスト
    "research_result",     # リサーチ結果
    "session_start",       # セッション開始
    "session_end",         # セッション終了
    "meeting_detected",    # 会議検知
    "summary_generated",   # サマリー生成完了
]

# プラグイン設定ファイルパス
PLUGINS_DIR = os.getenv(
    'MEETING_ASSISTANT_CONFIG_DIR',
    os.path.dirname(__file__)
)
PLUGINS_FILE = os.path.join(PLUGINS_DIR, 'plugins.json')


class PluginConfig:
    """プラグイン設定"""

    def __init__(self, data: Dict[str, Any]):
        self.name: str = data["name"]
        self.protocol: str = data["protocol"]  # websocket | pipe | webhook | exec
        self.endpoint: str = data.get("endpoint", "")
        self.events: List[str] = data.get("events", [])
        self.enabled: bool = data.get("enabled", True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "protocol": self.protocol,
            "endpoint": self.endpoint,
            "events": self.events,
            "enabled": self.enabled,
        }

    def accepts_event(self, event_type: str) -> bool:
        """このプラグインが指定イベントを購読しているか"""
        if not self.enabled:
            return False
        # eventsが空の場合は全イベント購読
        return len(self.events) == 0 or event_type in self.events


class PluginManager:
    """プラグインマネージャー: イベントのファンアウト配信"""

    def __init__(self):
        self.plugins: List[PluginConfig] = []
        # WebSocket購読クライアント: {websocket: set of subscribed events}
        self.ws_clients: Dict[Any, Set[str]] = {}
        # Pipeプロセス: {plugin_name: subprocess.Popen}
        self.pipe_processes: Dict[str, subprocess.Popen] = {}
        self._http_client = None
        self.load_plugins()

    def load_plugins(self):
        """plugins.json からプラグイン設定を読み込み"""
        if not os.path.exists(PLUGINS_FILE):
            self.plugins = []
            logger.info("📦 No plugins.json found, starting with empty plugin list")
            return

        try:
            with open(PLUGINS_FILE, 'r') as f:
                data = json.load(f)
            self.plugins = [PluginConfig(p) for p in data.get("plugins", [])]
            logger.info(f"📦 Loaded {len(self.plugins)} plugins from plugins.json")
            for p in self.plugins:
                status = "✅" if p.enabled else "⏸️"
                logger.info(f"   {status} {p.name} ({p.protocol}) -> {p.events or 'all'}")
        except Exception as e:
            logger.error(f"❌ Failed to load plugins.json: {e}")
            self.plugins = []

    def save_plugins(self):
        """プラグイン設定を plugins.json に保存"""
        data = {"plugins": [p.to_dict() for p in self.plugins]}
        try:
            with open(PLUGINS_FILE, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"💾 Saved {len(self.plugins)} plugins to plugins.json")
        except Exception as e:
            logger.error(f"❌ Failed to save plugins.json: {e}")

    # --- プラグイン CRUD ---

    def add_plugin(self, plugin_data: Dict[str, Any]) -> PluginConfig:
        """プラグインを追加"""
        plugin = PluginConfig(plugin_data)
        # 同名プラグインがあれば上書き
        self.plugins = [p for p in self.plugins if p.name != plugin.name]
        self.plugins.append(plugin)
        self.save_plugins()
        logger.info(f"➕ Plugin added: {plugin.name}")
        return plugin

    def remove_plugin(self, name: str) -> bool:
        """プラグインを削除"""
        before = len(self.plugins)
        self.plugins = [p for p in self.plugins if p.name != name]
        if len(self.plugins) < before:
            self._stop_pipe_process(name)
            self.save_plugins()
            logger.info(f"🗑️ Plugin removed: {name}")
            return True
        return False

    def update_plugin(self, name: str, updates: Dict[str, Any]) -> Optional[PluginConfig]:
        """プラグインを更新"""
        for p in self.plugins:
            if p.name == name:
                if "protocol" in updates:
                    p.protocol = updates["protocol"]
                if "endpoint" in updates:
                    p.endpoint = updates["endpoint"]
                if "events" in updates:
                    p.events = updates["events"]
                if "enabled" in updates:
                    p.enabled = updates["enabled"]
                self.save_plugins()
                logger.info(f"✏️ Plugin updated: {name}")
                return p
        return None

    def get_plugin(self, name: str) -> Optional[PluginConfig]:
        """プラグインを取得"""
        for p in self.plugins:
            if p.name == name:
                return p
        return None

    def list_plugins(self) -> List[Dict[str, Any]]:
        """全プラグイン一覧"""
        return [p.to_dict() for p in self.plugins]

    # --- イベント配信 ---

    async def emit(self, event_type: str, data: Dict[str, Any]):
        """
        イベントをファンアウト配信

        Args:
            event_type: イベント種別 (transcription, research_result, etc.)
            data: イベントデータ
        """
        event = {
            "event": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        }
        event_json = json.dumps(event, ensure_ascii=False)

        # 1. WebSocket購読クライアントに配信
        await self._emit_websocket(event_type, event_json)

        # 2. 登録済みプラグインに配信
        tasks = []
        for plugin in self.plugins:
            if plugin.accepts_event(event_type):
                tasks.append(self._deliver_to_plugin(plugin, event_type, event_json, event))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _emit_websocket(self, event_type: str, event_json: str):
        """WebSocket購読クライアントに配信"""
        disconnected = set()
        for ws, subscribed_events in self.ws_clients.items():
            # 購読イベントが空 = 全イベント購読
            if len(subscribed_events) == 0 or event_type in subscribed_events:
                try:
                    await ws.send_text(event_json)
                except Exception:
                    disconnected.add(ws)

        for ws in disconnected:
            self.ws_clients.pop(ws, None)

    async def _deliver_to_plugin(
        self, plugin: PluginConfig, event_type: str, event_json: str, event: Dict
    ):
        """個別プラグインへの配信"""
        try:
            if plugin.protocol == "webhook":
                await self._deliver_webhook(plugin, event_json)
            elif plugin.protocol == "pipe":
                await self._deliver_pipe(plugin, event_json)
            elif plugin.protocol == "exec":
                await self._deliver_exec(plugin, event_type, event)
            elif plugin.protocol == "websocket":
                # WebSocketプロトコルのプラグインは /ws/plugins エンドポイント経由
                # (ws_clients で管理されるため、ここでは何もしない)
                pass
        except Exception as e:
            logger.error(f"❌ [{plugin.name}] Delivery failed ({plugin.protocol}): {e}")

    async def _deliver_webhook(self, plugin: PluginConfig, event_json: str):
        """HTTP webhook 配信"""
        if not plugin.endpoint:
            return

        try:
            import aiohttp
            if self._http_client is None:
                self._http_client = aiohttp.ClientSession()

            async with self._http_client.post(
                plugin.endpoint,
                data=event_json,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status >= 400:
                    logger.warning(
                        f"⚠️ [{plugin.name}] Webhook returned {resp.status}"
                    )
        except ImportError:
            # aiohttp がない場合は httpx を試す
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        plugin.endpoint,
                        content=event_json,
                        headers={"Content-Type": "application/json"},
                    )
                    if resp.status_code >= 400:
                        logger.warning(
                            f"⚠️ [{plugin.name}] Webhook returned {resp.status_code}"
                        )
            except ImportError:
                logger.error(
                    f"❌ [{plugin.name}] No HTTP client available (install aiohttp or httpx)"
                )
        except Exception as e:
            logger.error(f"❌ [{plugin.name}] Webhook error: {e}")

    async def _deliver_pipe(self, plugin: PluginConfig, event_json: str):
        """Shell pipe 配信 (プラグインプロセスのstdinにJSON Linesで流す)"""
        if not plugin.endpoint:
            return

        proc = self.pipe_processes.get(plugin.name)

        # プロセスが起動していないか終了している場合、起動
        if proc is None or proc.poll() is not None:
            try:
                proc = subprocess.Popen(
                    plugin.endpoint,
                    shell=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.pipe_processes[plugin.name] = proc
                logger.info(f"🔧 [{plugin.name}] Pipe process started: {plugin.endpoint}")
            except Exception as e:
                logger.error(f"❌ [{plugin.name}] Failed to start pipe process: {e}")
                return

        # stdin に書き込み
        try:
            line = event_json + "\n"
            await asyncio.to_thread(proc.stdin.write, line.encode('utf-8'))
            await asyncio.to_thread(proc.stdin.flush)
        except (BrokenPipeError, OSError) as e:
            logger.warning(f"⚠️ [{plugin.name}] Pipe broken, will restart: {e}")
            self._stop_pipe_process(plugin.name)

    async def _deliver_exec(self, plugin: PluginConfig, event_type: str, event: Dict):
        """プロセス起動型配信 (イベント発生時にコマンド実行)"""
        if not plugin.endpoint:
            return

        env = os.environ.copy()
        env["MEETING_EVENT_TYPE"] = event_type
        env["MEETING_EVENT_DATA"] = json.dumps(event["data"], ensure_ascii=False)
        env["MEETING_EVENT_TIMESTAMP"] = event["timestamp"]

        try:
            proc = await asyncio.create_subprocess_shell(
                plugin.endpoint,
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            # タイムアウト付きで待機（最大10秒）
            try:
                await asyncio.wait_for(proc.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                proc.kill()
                logger.warning(f"⚠️ [{plugin.name}] Exec timeout, killed")
        except Exception as e:
            logger.error(f"❌ [{plugin.name}] Exec error: {e}")

    # --- WebSocket クライアント管理 ---

    def register_ws_client(self, websocket, events: List[str] = None):
        """WebSocket購読クライアントを登録"""
        self.ws_clients[websocket] = set(events or [])
        logger.info(
            f"🔌 Plugin WS client connected (events={events or 'all'}). "
            f"Total: {len(self.ws_clients)}"
        )

    def unregister_ws_client(self, websocket):
        """WebSocket購読クライアントを解除"""
        self.ws_clients.pop(websocket, None)
        logger.info(f"🔌 Plugin WS client disconnected. Total: {len(self.ws_clients)}")

    # --- クリーンアップ ---

    def _stop_pipe_process(self, name: str):
        """Pipeプロセスを停止"""
        proc = self.pipe_processes.pop(name, None)
        if proc and proc.poll() is None:
            try:
                proc.stdin.close()
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                proc.kill()

    async def cleanup(self):
        """全リソースのクリーンアップ"""
        # Pipeプロセスの停止
        for name in list(self.pipe_processes.keys()):
            self._stop_pipe_process(name)

        # HTTPクライアントのクローズ
        if self._http_client:
            try:
                await self._http_client.close()
            except Exception:
                pass
            self._http_client = None

        # WebSocketクライアントのクリア
        self.ws_clients.clear()

        logger.info("🧹 PluginManager cleaned up")

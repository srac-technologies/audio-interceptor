#!/usr/bin/env python3
"""
簡易テストスクリプト - 仮想デバイスの作成とクリーンアップのみテスト
"""

import sys
import time
import subprocess

def test_virtual_devices():
    print("Testing virtual device setup...")
    
    # 仮想スピーカーを作成
    result = subprocess.run([
        "pactl", "load-module", "module-null-sink",
        "sink_name=test_virtual_sink",
        "sink_properties=device.description='Test_Virtual_Sink'"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"❌ Failed to create virtual sink: {result.stderr}")
        return False
    
    sink_module_id = result.stdout.strip()
    print(f"✅ Created virtual sink (module {sink_module_id})")
    
    # 仮想マイクを作成
    result = subprocess.run([
        "pactl", "load-module", "module-null-source",
        "source_name=test_virtual_source",
        "source_properties=device.description='Test_Virtual_Source'"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"❌ Failed to create virtual source: {result.stderr}")
        subprocess.run(["pactl", "unload-module", sink_module_id], stderr=subprocess.DEVNULL)
        return False
    
    source_module_id = result.stdout.strip()
    print(f"✅ Created virtual source (module {source_module_id})")
    
    # デバイスが作成されたか確認
    print("\n📋 Available sinks:")
    subprocess.run(["pactl", "list", "short", "sinks"])
    
    print("\n📋 Available sources:")
    subprocess.run(["pactl", "list", "short", "sources"])
    
    # 少し待つ
    print("\n⏳ Waiting 3 seconds...")
    time.sleep(3)
    
    # クリーンアップ
    print("\n🧹 Cleaning up...")
    subprocess.run(["pactl", "unload-module", sink_module_id], stderr=subprocess.DEVNULL)
    subprocess.run(["pactl", "unload-module", source_module_id], stderr=subprocess.DEVNULL)
    print("✅ Cleanup complete")
    
    return True

if __name__ == "__main__":
    try:
        success = test_virtual_devices()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Test failed: {e}")
        sys.exit(1)

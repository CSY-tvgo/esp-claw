#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


UAC_FILE = 'managed_components/espressif__usb_host_uac/uac_host.c'
C_FILE = 'managed_components/espressif__esp_board_manager/src/esp_board_device.c'
H_FILE = 'managed_components/espressif__esp_board_manager/include/esp_board_device.h'
GEN_BOARD_DEVICE_CONFIG_FILE = 'components/gen_bmgr_codes/gen_board_device_config.c'
GEN_BOARD_PERIPH_CONFIG_FILE = 'components/gen_bmgr_codes/gen_board_periph_config.c'

UPDATE_CONFIG_FUNCTION = """esp_err_t esp_board_device_update_config(const char *name, const void *config)
{
    ESP_BOARD_RETURN_ON_FALSE(name && config, ESP_BOARD_ERR_DEVICE_INVALID_ARG, TAG, "Invalid args");
    /* Find device descriptor */
    esp_board_device_desc_t *desc = (esp_board_device_desc_t*)esp_board_find_device_desc(name);
    ESP_BOARD_RETURN_ON_DEVICE_NOT_FOUND(desc, name, TAG, "Device descriptor %s not found", name);

    if (!desc->cfg) {
        ESP_LOGW(TAG, "Device %s has no config, force to update", name);
    }

    desc->cfg = config;
    ESP_LOGI(TAG, "Device %s config updated: %p (size: %d)", name, desc->cfg, desc->cfg_size);
    return ESP_OK;
}
"""

UPDATE_CONFIG_DECLARATION = 'esp_err_t esp_board_device_update_config(const char *name, const void *config);\n'
UAC_PSRAM_LINE = '            || esp_ptr_in_psram(ptr)\n'
UAC_PSRAM_COMMENTED_LINE = '            // || esp_ptr_in_psram(ptr)\n'
BOARD_DEVICE_ARRAY_CONST_LINE = 'const esp_board_device_desc_t g_esp_board_devices'
BOARD_DEVICE_ARRAY_MUTABLE_LINE = 'esp_board_device_desc_t g_esp_board_devices'

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Insert esp_board_device_update_config() into esp_board_manager sources.'
    )
    parser.add_argument(
        '--project-dir',
        default='.',
        help='Path to the project directory. Defaults to the current directory.',
    )
    return parser.parse_args()


def fail(message: str) -> None:
    raise RuntimeError(message)


def ensure_contains(path: Path, needle: str) -> str:
    try:
        content = path.read_text(encoding='utf-8')
    except FileNotFoundError as exc:
        raise RuntimeError(f'Missing file: {path}') from exc
    if needle not in content:
        fail(f'Expected content not found in {path}: {needle}')
    return content


def write_if_changed(path: Path, original: str, updated: str) -> bool:
    if updated == original:
        return False
    path.write_text(updated, encoding='utf-8')
    return True


def patch_c_file(path: Path) -> bool:
    content = ensure_contains(path, 'esp_board_device_get_handle')
    if 'esp_board_device_update_config(' in content:
        return False

    anchor = """esp_err_t esp_board_device_get_config(const char *name, void **config)
"""
    if anchor not in content:
        fail(f'Anchor not found in {path}: {anchor.strip()}')

    updated = content.replace(anchor, f'{UPDATE_CONFIG_FUNCTION}\n{anchor}', 1)
    return write_if_changed(path, content, updated)


def patch_h_file(path: Path) -> bool:
    content = ensure_contains(path, 'esp_board_device_get_config')
    if 'esp_board_device_update_config(' in content:
        return False

    anchor = 'esp_err_t esp_board_device_get_config(const char *name, void **config);\n'
    if anchor not in content:
        fail(f'Anchor not found in {path}: {anchor.strip()}')

    updated = content.replace(anchor, f'{anchor}\n{UPDATE_CONFIG_DECLARATION}', 1)
    return write_if_changed(path, content, updated)


def patch_uac_file(path: Path) -> bool:
    if path.exists() is False:
        print(f'File {path} does not exist, skipping patch.')
        return False
    content = ensure_contains(path, 'ptr_is_writable')
    if UAC_PSRAM_COMMENTED_LINE in content:
        return False
    if UAC_PSRAM_LINE not in content:
        fail(f'Target line not found in {path}: {UAC_PSRAM_LINE.strip()}')

    updated = content.replace(UAC_PSRAM_LINE, UAC_PSRAM_COMMENTED_LINE, 1)
    return write_if_changed(path, content, updated)


def patch_gen_board_device_config_file(path: Path) -> bool:
    content = ensure_contains(path, 'g_esp_board_devices')

    if BOARD_DEVICE_ARRAY_CONST_LINE not in content:
        return False

    updated = content.replace(BOARD_DEVICE_ARRAY_CONST_LINE, BOARD_DEVICE_ARRAY_MUTABLE_LINE, 1)
    return write_if_changed(path, content, updated)


def patch_gen_board_periph_config_file(path: Path) -> bool:
    """Remove deprecated ESP-IDF <v5.3 I2S struct fields from the generated peripheral config.

    ESP-IDF v5.3 removed ``ext_clk_freq_hz`` from ``i2s_std_clk_config_t``, and removed
    ``left_align``, ``big_endian``, and ``bit_order_lsb`` from ``i2s_std_slot_config_t``.
    The esp_board_manager code generator still emits these fields, causing compilation
    errors when building against IDF v5.3+.

    The generator also emits a default ``.mclk_multiple`` line *before*
    ``.ext_clk_freq_hz``, then a second ``.mclk_multiple`` line (user value) immediately
    after.  Removing only ``.ext_clk_freq_hz`` would leave a duplicate initializer, so
    both the ``ext_clk_freq_hz`` line and the subsequent ``mclk_multiple`` line are
    dropped together (the earlier default ``mclk_multiple`` remains and carries the
    correct value).
    """
    if not path.exists():
        print(f'File {path} does not exist, skipping patch.')
        return False

    content = path.read_text(encoding='utf-8')

    if not any(
        field in content
        for field in ('ext_clk_freq_hz', 'left_align', 'big_endian', 'bit_order_lsb')
    ):
        return False

    updated = content

    # Remove `.ext_clk_freq_hz = <val>,` together with the immediately following
    # `.mclk_multiple = <val>,` line (the duplicate generated by the code generator).
    updated = re.sub(
        r'^[ \t]*\.ext_clk_freq_hz[ \t]*=[^\n]*\n[ \t]*\.mclk_multiple[ \t]*=[^\n]*\n',
        '',
        updated,
        flags=re.MULTILINE,
    )

    # Remove deprecated i2s_std_slot_config_t fields (removed in IDF v5.3).
    updated = re.sub(
        r'^[ \t]*\.(left_align|big_endian|bit_order_lsb)[ \t]*=[^\n]*\n',
        '',
        updated,
        flags=re.MULTILINE,
    )

    return write_if_changed(path, content, updated)


def main() -> int:
    args = parse_args()
    project_dir = Path(args.project_dir).resolve()
    c_path = project_dir / C_FILE
    h_path = project_dir / H_FILE
    uac_path = project_dir / UAC_FILE
    gen_board_device_config_path = project_dir / GEN_BOARD_DEVICE_CONFIG_FILE
    gen_board_periph_config_path = project_dir / GEN_BOARD_PERIPH_CONFIG_FILE

    changed_files: list[Path] = []
    if patch_c_file(c_path):
        changed_files.append(c_path)
    if patch_h_file(h_path):
        changed_files.append(h_path)
    if patch_uac_file(uac_path):
        changed_files.append(uac_path)
    if patch_gen_board_device_config_file(gen_board_device_config_path):
        changed_files.append(gen_board_device_config_path)
    if patch_gen_board_periph_config_file(gen_board_periph_config_path):
        changed_files.append(gen_board_periph_config_path)

    if not changed_files:
        print('No changes needed.')
        return 0

    for path in changed_files:
        print(f'Updated {path.relative_to(project_dir)}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        raise SystemExit(1)

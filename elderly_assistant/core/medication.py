# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime
from utils.logger import setup_logger

# 中文数字映射，用于解析中文剂量（如"两片"、"半片"）
CN_NUM = {'半': 0.5, '一': 1, '两': 2, '二': 2, '三': 3, '四': 4,
          '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def _parse_dosage(s):
    """解析剂量字符串，支持阿拉伯数字与中文数字"""
    import re
    nums = re.findall(r'\d+', str(s))
    if nums:
        return int(nums[0])
    # 尝试中文数字
    for k, v in CN_NUM.items():
        if k in str(s):
            return v
    return 0


class MedicationManager:
    def __init__(self, data_path="data/medications.json"):
        self.data_path = data_path
        self.logger = setup_logger()
        self.medications = self.load()

    def load(self):
        """加载药品数据，若文件不存在或损坏则返回空列表并修复文件"""
        try:
            if os.path.exists(self.data_path):
                with open(self.data_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        data = json.loads(content)
                        if isinstance(data, list):
                            return data
                        else:
                            # 数据格式异常时先备份原文件，避免直接覆盖丢失数据
                            self.logger.error(f"药品数据格式错误，期望列表但得到 {type(data)}，备份原文件")
                            import shutil
                            shutil.copy2(self.data_path, self.data_path + '.bak')
        except json.JSONDecodeError as e:
            self.logger.error(f"药品数据 JSON 解析失败: {e}")
            # JSON 解析失败也备份原文件
            if os.path.exists(self.data_path):
                import shutil
                shutil.copy2(self.data_path, self.data_path + '.bak')
        except Exception as e:
            self.logger.error(f"加载药品数据失败: {e}")

        os.makedirs(os.path.dirname(self.data_path) or ".", exist_ok=True)
        try:
            with open(self.data_path, 'w', encoding='utf-8') as f:
                json.dump([], f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"创建默认药品文件失败: {e}")
        return []

    def save(self):
        """保存药品数据到文件（P11：临时文件 + os.replace 原子写入）"""
        try:
            os.makedirs(os.path.dirname(self.data_path) or ".", exist_ok=True)
            tmp = self.data_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.medications, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.data_path)
        except Exception as e:
            self.logger.error(f"保存药品数据失败: {e}")

    def add_medication(self, name, total_quantity, dosage_per_use, reminder_days=5):
        """添加药品"""
        for med in self.medications:
            if med.get('name') == name:
                self.logger.warning(f"药品 {name} 已存在，将更新")
                med['total'] = total_quantity
                med['dosage_per_use'] = dosage_per_use
                med['reminder_days'] = reminder_days
                self.save()
                return

        self.medications.append({
            "name": name,
            "total": total_quantity,
            "dosage_per_use": dosage_per_use,
            "remaining": total_quantity,
            "reminder_days": reminder_days,
            "last_updated": datetime.now().isoformat()
        })
        self.save()

    def consume(self, med_name, dosage_str):
        """消耗药品（从提醒确认调用）"""
        try:
            # 使用 _parse_dosage 支持中文数字（如"两片"、"半片"）
            dose = float(_parse_dosage(dosage_str))
            if dose <= 0:
                return False

            for med in self.medications:
                if med.get('name') == med_name:
                    med['remaining'] = max(0, med.get('remaining', 0) - dose)
                    med['last_updated'] = datetime.now().isoformat()
                    self.logger.info(f"药品消耗: {med_name} -{dose}, 剩余 {med['remaining']}")
                    self.check_low(med)
                    self.save()
                    return True
            self.logger.warning(f"未找到药品: {med_name}")
            return False
        except Exception as e:
            self.logger.error(f"消耗药品失败: {e}")
            return False

    def check_low(self, med):
        """检查药品是否低于提醒阈值，返回 (药品名, 剩余天数) 或 (None, None)"""
        try:
            dosage = med.get('dosage_per_use', 0)
            if dosage <= 0:
                return None, None
            remaining = med.get('remaining', 0)
            days_left = remaining / dosage
            threshold = med.get('reminder_days', 5)
            if days_left < threshold:
                return med.get('name'), days_left
        except Exception as e:
            self.logger.error(f"低库存检查出错: {e}")
        return None, None

    def get_all(self):
        return self.medications if self.medications else []
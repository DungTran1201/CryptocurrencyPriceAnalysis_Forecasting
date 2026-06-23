import logging
import sys
import time
import functools

# 1. Lớp cha: Cấu hình khung sườn chung
class BaseLogger:
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # Chỉ tạo handler nếu chưa có (tránh duplicate log)
        if not self.logger.handlers:
            formatter = logging.Formatter('%(asctime)s - [%(name)s] - %(levelname)s: %(message)s')
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

# 2. Lớp con: Log vận hành thông thường
class OperationLogger(BaseLogger):
    def info(self, msg): self.logger.info(msg)
    def debug(self, msg): self.logger.debug(msg)
    def warning(self, msg): self.logger.warning(msg)

# 3. Lớp con: Chuyên xử lý ngoại lệ
class ExceptionLogger(BaseLogger):
    def handle(self, e: Exception, context: str):
        self.logger.error(f"EXCEPTION in {context} | {str(e)}", exc_info=True)
        raise e

# 4. Lớp con: Chuyên theo dõi hiệu năng
class PerformanceLogger(BaseLogger):
    def track(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            self.logger.debug(f"START: {func.__name__}")
            try:
                result = func(*args, **kwargs)
                end_time = time.perf_counter()
                self.logger.info(f"DONE: {func.__name__} | Time: {end_time - start_time:.4f}s")
                return result
            except Exception as e:
                self.logger.error(f"FAIL: {func.__name__} after {time.perf_counter() - start_time:.4f}s")
                raise e
        return wrapper

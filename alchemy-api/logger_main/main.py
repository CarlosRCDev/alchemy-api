from os import path, mkdir, remove
from glob import glob
from pathlib import Path

from .logger_paralel import ParallelTimedRotatingFileHandler
import logging

# from ..utils.main_utils import SingletonMeta

class DummyLogger:
    def __init__(self, *args, **kwargs):
        pass
    
    def error(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass
    
    def debug(self, *args, **kwargs):
        pass

    def traza(self, *args, **kwargs):
        pass

    def ret_logger(self, *args, **kwargs):
        return self
    
    def isEnabledFor(self, *args, **kwargs):
        pass

# @singleton
class Logger: #(metaclass=SingletonMeta)
    def __init__(self, config_global_logs):
        # name_file = "download"
        name  = "dblog"

        self.logger = logging.getLogger(name)
        level = logging.getLevelName(config_global_logs["level_log"])
        self.logger.setLevel(level)
        """Format of text inside log, ascitime, level of log and message, and last the format of datetime in logger name"""
        formatter = logging.Formatter(fmt='%(asctime)s %(levelname)-8s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

        self.path_log = config_global_logs["log_path"]
        self.create_folder(self.path_log)

        handler = ParallelTimedRotatingFileHandler(filename=config_global_logs["log_path"], when='D', backupCount=config_global_logs["backup_count"], encoding="utf-8")

        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        self.logger.info(f"-----Start Application: LEVEL:{config_global_logs['level_log']}-----")

    def traza(self, traza_str):
        """
        Funcion to write in log, whatever

        Parameters
        ----------
        traza: str
            String to write    
        """
        print('traza: ' + str(traza_str))
        self.logger.info('traza:' + str(traza_str))

    def ret_logger(self):
        return  self.logger

    def create_folder(self, file_path):
        dir_path = path.dirname(file_path)
        if not path.exists(dir_path):
            print("Creating folder: " + dir_path)
            mkdir(dir_path)
    
    def list_logs(self):
        return [Path(x).stem.split(".")[-1] for x in glob(f"{self.path_log}.*.log")]

    def date_logs(self, date):
        path_log = f"{self.path_log}.{date}.log"
        if not path.exists(path_log):
            return False
        else:
            return path_log

    def delete_date_logs(self, date):
        actual_log = Path(self.logger.handlers[0].baseFilename).stem.split(".")[-1]
        if date == actual_log:
            return False
        path_log = f"{self.path_log}.{date}.log"
        if not path.exists(path_log):
            return None
        else:
            remove(path_log)
            return True
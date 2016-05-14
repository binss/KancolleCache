# !/usr/bin/env python
# -*- coding: utf-8 -*-
#
# FileName:      log.py
# Author:        binss
# Create:        2016-05-14 10:15:07
# Description:   No Description
#


from tornado.log import LogFormatter
import logging
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 日志文件名前缀
LOG_FILENAME_PREFIX = 'logs/'
# log文件的最大尺寸(大于就会换文件，又称滚动)
LOG_MAX_BYTES = 1024 * 1024 * 10
# log文件个数
LOG_BACKUP_COUNT = 50



def LogFactory(name, level=logging.DEBUG):
    log = logging.getLogger()
    log.setLevel(level)

    # # 输出到日志文件
    # filename = LOG_FILENAME_PREFIX + name + '.log'
    # file_handler = logging.handlers.RotatingFileHandler(filename, mode='a', maxBytes=LOG_MAX_BYTES,
    #                                                     backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
    # file_handler.setFormatter(LogFormatter(color=False))
    # log.addHandler(file_handler)

    # 输出到终端
    terminal_handler = logging.StreamHandler(sys.stderr)
    terminal_handler.setFormatter(LogFormatter())
    log.addHandler(terminal_handler)
    return log


logger = LogFactory('webrtc')


def test():
    logger.debug('\uffe5')



if __name__ == '__main__':
    test()

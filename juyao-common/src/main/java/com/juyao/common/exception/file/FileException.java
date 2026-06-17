package com.juyao.common.exception.file;

import com.juyao.common.exception.base.BaseException;

/**
 * 文件信息异常类
 * 
 * @author juyao
 */
public class FileException extends BaseException{
    private static final long serialVersionUID = 1L;

    public FileException(String code, Object[] args){
        super("file", code, args, null);
    }

}

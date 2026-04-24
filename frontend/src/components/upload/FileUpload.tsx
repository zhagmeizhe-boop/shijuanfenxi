"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { Upload, FileText, X, Loader2 } from "lucide-react";
import toast from "react-hot-toast";
import { AnalysisResult } from "@/types/analysis";

interface FileUploadProps {
  onUploadSuccess: (result: AnalysisResult) => void;
  isAnalyzing: boolean;
  setIsAnalyzing: (value: boolean) => void;
}

const ALLOWED_TYPES = {
  'application/pdf': ['.pdf'],
  'image/png': ['.png'],
  'image/jpeg': ['.jpg', '.jpeg'],
};

const MAX_SIZE = 10 * 1024 * 1024; // 10MB

export function FileUpload({
  onUploadSuccess,
  isAnalyzing,
  setIsAnalyzing
}: FileUploadProps) {
  const [file, setFile] = useState<File | null>(null);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      const selectedFile = acceptedFiles[0];

      if (selectedFile.size > MAX_SIZE) {
        toast.error(`文件大小超过限制 (最大 ${MAX_SIZE / 1024 / 1024}MB)`);
        return;
      }

      setFile(selectedFile);
      toast.success(`已选择文件: ${selectedFile.name}`);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop,
    accept: ALLOWED_TYPES,
    maxFiles: 1,
    multiple: false,
  });

  const handleUpload = async () => {
    if (!file) {
      toast.error("请先选择文件");
      return;
    }

    setIsAnalyzing(true);
    const loadingToast = toast.loading("正在上传并分析试卷...");

    try {
      const formData = new FormData();
      formData.append("file", file);

      // 模拟 API 调用（后续替换为真实 API）
      await new Promise(resolve => setTimeout(resolve, 3000));

      // 模拟分析结果
      const mockResult: AnalysisResult = {
        id: "mock-analysis-001",
        paper_info: {
          title: "2024年小学五年级数学分班考试",
          grade: "五年级",
          subject: "数学",
          total_score: 100,
          question_count: 25,
          estimated_time: 60,
          source: "XX教育集团",
          created_at: new Date().toISOString(),
        },
        dimensions: {
          computation: 85,
          concept: 78,
          logic: 72,
          spatial: 68,
          application: 75,
          innovation: 65,
        },
        difficulty: {
          overall: "medium",
          score: 65,
          description: "整体难度适中，适合五年级下学期学生",
        },
        target_students: ["成绩中等偏上学生", "基础扎实欲拔高学生"],
        comparison: {
          avg_score: 72,
          percentile: 68,
          benchmark: "区域五年级平均水平",
        },
        knowledge_points: [
          { name: "四则运算", category: "数与代数", count: 8, difficulty_avg: 3.2 },
          { name: "分数运算", category: "数与代数", count: 5, difficulty_avg: 3.8 },
          { name: "图形面积", category: "图形与几何", count: 4, difficulty_avg: 4.1 },
          { name: "简单方程", category: "数与代数", count: 3, difficulty_avg: 4.5 },
        ],
        representative_questions: [
          { id: "q1", dimension: "computation", content: "计算: 3/4 + 2/5", difficulty: 3, score: 4 },
          { id: "q2", dimension: "logic", content: "找规律填空: 2, 6, 12, 20, __", difficulty: 4, score: 5 },
        ],
        generated_at: new Date().toISOString(),
      };

      toast.dismiss(loadingToast);
      toast.success("分析完成！");
      onUploadSuccess(mockResult);
    } catch (error) {
      toast.dismiss(loadingToast);
      toast.error("分析失败，请重试");
      console.error(error);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const clearFile = () => {
    setFile(null);
  };

  return (
    <div className="bg-white rounded-2xl shadow-xl shadow-gray-200/50 overflow-hidden">
      <div className="p-8">
        {/* Dropzone */}
        {!file ? (
          <div
            {...getRootProps()}
            className={`
              relative border-2 border-dashed rounded-xl p-12 text-center cursor-pointer
              transition-all duration-300 ease-out
              ${isDragActive && !isDragReject
                ? 'border-blue-500 bg-blue-50 scale-[1.02]'
                : isDragReject
                ? 'border-red-400 bg-red-50'
                : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'
              }
            `}
          >
            <input {...getInputProps()} />
            <div className="space-y-4">
              <div className={`
                w-20 h-20 mx-auto rounded-full flex items-center justify-center
                transition-all duration-300
                ${isDragActive ? 'bg-blue-100 scale-110' : 'bg-gray-100'}
              `}>
                <Upload className={`
                  w-10 h-10 transition-colors duration-300
                  ${isDragActive ? 'text-blue-600' : 'text-gray-400'}
                `} />
              </div>
              <div>
                <p className="text-lg font-medium text-gray-900">
                  {isDragActive ? '释放文件以上传' : '点击或拖拽文件到此处'}
                </p>
                <p className="text-sm text-gray-500 mt-1">
                  支持 PDF、JPG、PNG 格式，文件大小不超过 10MB
                </p>
              </div>
            </div>
          </div>
        ) : (
          /* Selected File Preview */
          <div className="space-y-6">
            <div className="flex items-center gap-4 p-4 bg-gray-50 rounded-xl">
              <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                <FileText className="w-6 h-6 text-blue-600" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-medium text-gray-900 truncate">{file.name}</p>
                <p className="text-sm text-gray-500">
                  {(file.size / 1024 / 1024).toFixed(2)} MB
                </p>
              </div>
              <button
                onClick={clearFile}
                disabled={isAnalyzing}
                className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Upload Button */}
            <button
              onClick={handleUpload}
              disabled={isAnalyzing}
              className="w-full py-4 bg-gradient-to-r from-blue-500 to-purple-600 text-white font-semibold rounded-xl shadow-lg shadow-blue-500/25 hover:shadow-xl hover:shadow-blue-500/30 hover:scale-[1.01] active:scale-[0.99] transition-all duration-200 disabled:opacity-70 disabled:cursor-not-allowed disabled:hover:scale-100 flex items-center justify-center gap-2"
            >
              {isAnalyzing ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>正在分析试卷...</span>
                </>
              ) : (
                <>
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                  </svg>
                  <span>开始六维分析</span>
                </>
              )}
            </button>

            <p className="text-center text-sm text-gray-500">
              分析过程可能需要 30-60 秒，请耐心等待
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

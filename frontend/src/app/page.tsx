"use client";

import { useState } from "react";
import { FileUpload } from "@/components/upload/FileUpload";
import { AnalysisReport } from "@/components/report/AnalysisReport";
import { AnalysisResult } from "@/types/analysis";

export default function Home() {
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const handleUploadSuccess = (result: AnalysisResult) => {
    setAnalysisResult(result);
    setIsAnalyzing(false);
  };

  return (
    <main className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      {/* Header */}
      <header className="bg-white/80 backdrop-blur-md border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center">
              <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
              </svg>
            </div>
            <div>
              <h1 className="text-xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                数学试卷六维分析
              </h1>
              <p className="text-xs text-gray-500">智能分析报告生成系统</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <a
              href="/api/docs"
              target="_blank"
              className="text-sm text-gray-600 hover:text-blue-600 transition-colors"
            >
              API 文档
            </a>
            <button className="bg-gradient-to-r from-blue-500 to-purple-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:shadow-lg hover:shadow-blue-500/25 transition-all">
              帮助中心
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        {!analysisResult ? (
          <div className="max-w-3xl mx-auto">
            {/* Hero Section */}
            <div className="text-center mb-12">
              <h2 className="text-4xl font-bold text-gray-900 mb-4">
                上传试卷，自动生成
                <span className="bg-gradient-to-r from-blue-500 to-purple-600 bg-clip-text text-transparent"> 六维分析报告</span>
              </h2>
              <p className="text-lg text-gray-600 max-w-2xl mx-auto">
                支持 PDF、JPG、PNG 格式，AI 自动识别题目、分析难度、评估六维能力，
                生成专业级试卷分析报告
              </p>
            </div>

            {/* Features */}
            <div className="grid grid-cols-3 gap-6 mb-12">
              {[
                { icon: '📄', title: '智能识别', desc: 'OCR 自动识别题目内容' },
                { icon: '📊', title: '六维评分', desc: '多维度能力评估模型' },
                { icon: '📈', title: '专业报告', desc: '生成 PDF 分析报告' },
              ].map((f, i) => (
                <div key={i} className="text-center p-4 bg-white/50 rounded-xl">
                  <div className="text-3xl mb-2">{f.icon}</div>
                  <h3 className="font-semibold text-gray-900">{f.title}</h3>
                  <p className="text-sm text-gray-500">{f.desc}</p>
                </div>
              ))}
            </div>

            {/* Upload Component */}
            <FileUpload
              onUploadSuccess={handleUploadSuccess}
              isAnalyzing={isAnalyzing}
              setIsAnalyzing={setIsAnalyzing}
            />
          </div>
        ) : (
          <AnalysisReport
            result={analysisResult}
            onReset={() => setAnalysisResult(null)}
          />
        )}
      </div>

      {/* Footer */}
      <footer className="bg-white border-t border-gray-200 mt-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex justify-between items-center">
            <p className="text-gray-500 text-sm">
              © 2024 小学数学分班考试卷六维分析系统. All rights reserved.
            </p>
            <div className="flex gap-4">
              <a href="#" className="text-gray-400 hover:text-gray-600 text-sm">隐私政策</a>
              <a href="#" className="text-gray-400 hover:text-gray-600 text-sm">使用条款</a>
              <a href="#" className="text-gray-400 hover:text-gray-600 text-sm">联系我们</a>
            </div>
          </div>
        </div>
      </footer>
    </main>
  );
}

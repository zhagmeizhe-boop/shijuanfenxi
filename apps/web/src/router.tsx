import { createBrowserRouter, Navigate } from 'react-router-dom';
import PDFUploadPageWrapper from './pages/PDFUploadPageWrapper';
import ReportPageWrapper from './pages/ReportPageWrapper';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <PDFUploadPageWrapper />,
  },
  {
    path: '/report/:id',
    element: <ReportPageWrapper />,
  },
  {
    path: '*',
    element: <Navigate to="/" replace />,
  },
]);

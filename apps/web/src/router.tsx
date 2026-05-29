import { createBrowserRouter, Navigate } from 'react-router-dom';
import AdminPapersPage from './pages/AdminPapersPage';
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
    path: '/admin/papers',
    element: <AdminPapersPage />,
  },
  {
    path: '*',
    element: <Navigate to="/" replace />,
  },
]);

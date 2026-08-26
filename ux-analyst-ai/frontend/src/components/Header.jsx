import React from 'react'
import { Link } from 'react-router-dom'

function Header() {
  return (
    <header className="bg-white shadow-sm border-b border-gray-200">
      <div className="container mx-auto px-4 py-4">
        <div className="flex items-center justify-between">
          <Link to="/" className="flex items-center space-x-2">
            <div className="w-8 h-8 bg-primary-600 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-sm">UX</span>
            </div>
            <span className="text-xl font-bold text-gray-900">UX Analyst AI</span>
          </Link>

          <nav className="hidden md:flex items-center space-x-6">
            <Link
              to="/"
              className="text-gray-600 hover:text-gray-900 transition-colors"
            >
              Home
            </Link>
            <a
              href="#features"
              className="text-gray-600 hover:text-gray-900 transition-colors"
            >
              Features
            </a>
            <a
              href="#how-it-works"
              className="text-gray-600 hover:text-gray-900 transition-colors"
            >
              How it Works
            </a>
          </nav>

          <div className="flex items-center space-x-4">
            <button className="btn btn-secondary">
              View Sample Report
            </button>
          </div>
        </div>
      </div>
    </header>
  )
}

export default Header
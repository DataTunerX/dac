"use client"

import { Component, type ErrorInfo, type ReactNode } from "react"
import { Button } from "@/components/ui/button"

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, errorInfo)
  }

  render() {
    if (this.state.hasError && this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback
      }
      return (
        <div className="flex flex-col items-center justify-center min-h-[280px] p-6 text-center">
          <p className="text-content font-medium mb-2">页面加载出错</p>
          <p className="text-sm text-content-muted mb-4 max-w-md">
            {this.state.error.message}
          </p>
          <Button
            type="button"
            variant="outline"
            onClick={() => this.setState({ hasError: false, error: null })}
          >
            重试
          </Button>
        </div>
      )
    }
    return this.props.children
  }
}

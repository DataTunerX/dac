"use client";

import { useEffect, useState } from "react";
import { getUserRole } from "@/lib/auth";
import { Button, ButtonProps } from "@/components/ui/button";

interface RbacButtonProps extends ButtonProps {
  requiredRole?: string;
  fallbackTitle?: string;
}

export function RbacButton({ 
  requiredRole = "admin", 
  fallbackTitle = "无权限",
  disabled,
  title,
  ...props 
}: RbacButtonProps) {
  const [role, setRole] = useState("user");

  useEffect(() => {
    setRole(getUserRole());
  }, []);

  const hasPermission = role === requiredRole;

  if (!hasPermission) {
    return (
      <Button
        {...props}
        disabled={true}
        title={fallbackTitle}
      />
    );
  }

  return <Button {...props} disabled={disabled} title={title} />;
}

export function RbacWrapper({ 
  children, 
  requiredRole = "admin",
  inverse = false
}: { 
  children: React.ReactNode; 
  requiredRole?: string; 
  inverse?: boolean;
}) {
  const [role, setRole] = useState("user");

  useEffect(() => {
    setRole(getUserRole());
  }, []);

  const hasRole = role === requiredRole;
  const shouldRender = inverse ? !hasRole : hasRole;

  if (!shouldRender) {
    return null;
  }

  return <>{children}</>;
}

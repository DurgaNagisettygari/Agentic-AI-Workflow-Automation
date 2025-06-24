"""
Workflow Orchestrator for AI Agent Coordination
Author: Durga D Nagisettygari
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import json
from enum import Enum
import uuid

logger = logging.getLogger(__name__)

class WorkflowStatus(Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class WorkflowStep:
    """Represents a single step in a workflow"""
    
    def __init__(self, step_id: str, agent_type: str, task: Dict[str, Any], dependencies: List[str] = None):
        self.step_id = step_id
        self.agent_type = agent_type
        self.task = task
        self.dependencies = dependencies or []
        self.status = WorkflowStatus.CREATED
        self.result = None
        self.started_at = None
        self.completed_at = None
        self.error = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "agent_type": self.agent_type,
            "task": self.task,
            "dependencies": self.dependencies,
            "status": self.status.value,
            "result": self.result,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error
        }

class Workflow:
    """Represents a complete workflow with multiple steps"""
    
    def __init__(self, workflow_id: str, name: str, description: str):
        self.workflow_id = workflow_id
        self.name = name
        self.description = description
        self.steps: Dict[str, WorkflowStep] = {}
        self.status = WorkflowStatus.CREATED
        self.created_at = datetime.now()
        self.started_at = None
        self.completed_at = None
        self.priority = 1
        self.metadata = {}
    
    def add_step(self, step: WorkflowStep):
        """Add a step to the workflow"""
        self.steps[step.step_id] = step
    
    def get_ready_steps(self) -> List[WorkflowStep]:
        """Get steps that are ready to execute (dependencies satisfied)"""
        ready_steps = []
        
        for step in self.steps.values():
            if step.status == WorkflowStatus.CREATED:
                # Check if all dependencies are completed
                dependencies_satisfied = all(
                    self.steps[dep_id].status == WorkflowStatus.COMPLETED
                    for dep_id in step.dependencies
                    if dep_id in self.steps
                )
                
                if dependencies_satisfied:
                    ready_steps.append(step)
        
        return ready_steps
    
    def is_completed(self) -> bool:
        """Check if all steps are completed"""
        return all(
            step.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]
            for step in self.steps.values()
        )
    
    def has_failed_steps(self) -> bool:
        """Check if any steps have failed"""
        return any(step.status == WorkflowStatus.FAILED for step in self.steps.values())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "priority": self.priority,
            "metadata": self.metadata,
            "steps": {step_id: step.to_dict() for step_id, step in self.steps.items()}
        }

class WorkflowOrchestrator:
    """Orchestrates workflow execution with dependency management"""
    
    def __init__(self, max_concurrent_steps: int = 5):
        self.workflows: Dict[str, Workflow] = {}
        self.max_concurrent_steps = max_concurrent_steps
        self.running_steps = 0
        self.execution_queue = asyncio.Queue()
        self.created_at = datetime.now()
        self.total_workflows_executed = 0
        self.successful_workflows = 0
    
    def create_workflow(self, name: str, description: str, steps_config: List[Dict[str, Any]]) -> str:
        """Create a new workflow"""
        workflow_id = str(uuid.uuid4())
        workflow = Workflow(workflow_id, name, description)
        
        # Create workflow steps
        for i, step_config in enumerate(steps_config):
            step_id = step_config.get("id", f"step_{i+1}")
            agent_type = step_config.get("agent", "data_retrieval")
            task = step_config.get("task", {})
            dependencies = step_config.get("dependencies", [])
            
            step = WorkflowStep(step_id, agent_type, task, dependencies)
            workflow.add_step(step)
        
        self.workflows[workflow_id] = workflow
        logger.info(f"Created workflow: {workflow_id} with {len(steps_config)} steps")
        
        return workflow_id
    
    async def execute_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Execute a workflow with dependency management"""
        if workflow_id not in self.workflows:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        workflow = self.workflows[workflow_id]
        
        if workflow.status == WorkflowStatus.RUNNING:
            raise ValueError(f"Workflow {workflow_id} is already running")
        
        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = datetime.now()
        self.total_workflows_executed += 1
        
        logger.info(f"Starting workflow execution: {workflow_id}")
        
        try:
            # Execute workflow steps with dependency management
            while not workflow.is_completed():
                ready_steps = workflow.get_ready_steps()
                
                if not ready_steps:
                    # No ready steps, check if we're stuck
                    if not any(step.status == WorkflowStatus.RUNNING for step in workflow.steps.values()):
                        # No running steps and no ready steps - workflow is stuck
                        workflow.status = WorkflowStatus.FAILED
                        logger.error(f"Workflow {workflow_id} is stuck - no ready or running steps")
                        break
                    
                    # Wait for running steps to complete
                    await asyncio.sleep(0.1)
                    continue
                
                # Execute ready steps (respecting concurrency limits)
                tasks = []
                for step in ready_steps[:self.max_concurrent_steps - self.running_steps]:
                    task = self._execute_step(workflow_id, step)
                    tasks.append(task)
                
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            
            # Determine final workflow status
            if workflow.has_failed_steps():
                workflow.status = WorkflowStatus.FAILED
                logger.error(f"Workflow {workflow_id} completed with failures")
            else:
                workflow.status = WorkflowStatus.COMPLETED
                workflow.completed_at = datetime.now()
                self.successful_workflows += 1
                logger.info(f"Workflow {workflow_id} completed successfully")
            
            return workflow.to_dict()
            
        except Exception as e:
            workflow.status = WorkflowStatus.FAILED
            logger.error(f"Workflow {workflow_id} failed with exception: {str(e)}")
            raise
    
    async def _execute_step(self, workflow_id: str, step: WorkflowStep):
        """Execute a single workflow step"""
        from agents import agent_manager
        
        self.running_steps += 1
        step.status = WorkflowStatus.RUNNING
        step.started_at = datetime.now()
        
        try:
            logger.info(f"Executing step {step.step_id} in workflow {workflow_id}")
            
            # Get the appropriate agent and execute the task
            if step.agent_type in agent_manager.agents:
                agent = agent_manager.agents[step.agent_type]
                result = await agent.execute(step.task)
                
                step.result = result
                step.status = WorkflowStatus.COMPLETED
                step.completed_at = datetime.now()
                
                logger.info(f"Step {step.step_id} completed successfully")
            else:
                raise ValueError(f"Unknown agent type: {step.agent_type}")
                
        except Exception as e:
            step.status = WorkflowStatus.FAILED
            step.error = str(e)
            step.completed_at = datetime.now()
            logger.error(f"Step {step.step_id} failed: {str(e)}")
        
        finally:
            self.running_steps -= 1
    
    def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get the current status of a workflow"""
        if workflow_id not in self.workflows:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        return self.workflows[workflow_id].to_dict()
    
    def pause_workflow(self, workflow_id: str):
        """Pause a running workflow"""
        if workflow_id not in self.workflows:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        workflow = self.workflows[workflow_id]
        if workflow.status == WorkflowStatus.RUNNING:
            workflow.status = WorkflowStatus.PAUSED
            logger.info(f"Paused workflow: {workflow_id}")
    
    def resume_workflow(self, workflow_id: str):
        """Resume a paused workflow"""
        if workflow_id not in self.workflows:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        workflow = self.workflows[workflow_id]
        if workflow.status == WorkflowStatus.PAUSED:
            workflow.status = WorkflowStatus.RUNNING
            logger.info(f"Resumed workflow: {workflow_id}")
    
    def cancel_workflow(self, workflow_id: str):
        """Cancel a workflow"""
        if workflow_id not in self.workflows:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        workflow = self.workflows[workflow_id]
        workflow.status = WorkflowStatus.CANCELLED
        workflow.completed_at = datetime.now()
        logger.info(f"Cancelled workflow: {workflow_id}")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get orchestrator performance metrics"""
        success_rate = (self.successful_workflows / self.total_workflows_executed * 100) if self.total_workflows_executed > 0 else 0
        
        return {
            "created_at": self.created_at,
            "total_workflows": len(self.workflows),
            "total_workflows_executed": self.total_workflows_executed,
            "successful_workflows": self.successful_workflows,
            "success_rate": success_rate,
            "running_workflows": len([w for w in self.workflows.values() if w.status == WorkflowStatus.RUNNING]),
            "max_concurrent_steps": self.max_concurrent_steps,
            "current_running_steps": self.running_steps
        }

# Global orchestrator instance
orchestrator = WorkflowOrchestrator()

# AI Use Case: Multi-Tenant Conversion Planning

## Overview

This document demonstrates how to use `knack-sleuth` app-summary with an AI agent to plan and estimate work where current objects don't exist.


### Hyopthetical

**The Problem:** Your manager/client says "We need to convert this from a single-tenant application to multi-tenant SaaS. Here's the business case, now estimate the work and give me a timeline."

In a nutshell, your app probably doesn't have an "organization" table. How to analyze the impact of adding an "organization" object and how to use AI to help.

In my experience, it's hard to convey useful Knack.app context to AI Agents/Chats.


You're facing a fundamental architectural change:
- You need to understand the true scope before committing to a timeline
- Some portion of your app/data model needs to be re-scoped around organizations/tenants
- If you are a solo-prenuer, freelancer, it may be hard to "bounce ideas" off someone.


**Weaknesses in my current state:**
- **knack-sleuth impact-analysis won't help** because the new tenant/organization objects don't exist yet
- **Checking individual objects one-by-one** leads to incomplete analysis and missed dependencies
- **I like to see the whole picture** before deciding on architecture and approach


**What I (You) Need:**
- **Comprehensive context** to understand existing architecture complexity
- **Risk identification** to spot bottlenecks and tightly-coupled areas that will be hard to change
- **Scoping analysis** to determine which objects are affected and how
- **Estimation help** to give management a defensible timeline
- **Collaborative reasoning** with an AI assistant to think through design tradeoffs


What I'm aiming at
**This is where knack-sleuth app-summary + AI comes in:** Generate your complete architectural blueprint, then use it as the foundation for planning conversations with an AI agent who can reason about scope, complexity, risks, and phasing.

## Workflow

### 1. Generate App Summary

First, generate a comprehensive JSON summary of your application:

```bash
knack-sleuth app-summary --app-id YOUR_APP_ID --format json > app_architecture.json
```

### 2. Provide Context to AI

Start a conversation with an AI agent (Claude, ChatGPT, etc.) with this prompt:

```
I'm planning to convert my single-tenant Knack application into a multi-tenant SaaS platform. 
I need your help scoping and estimating the work involved.

Here's my complete application architecture:

<paste entire contents of app_architecture.json>

I'd like to walk through the conversion with you. Let me describe what I'm thinking, and you can help me 
understand the architectural implications, risks, and effort involved.
```

### 3. Have a Conversation

The AI now has complete architectural context and can help you reason through.


... Will update this after some real-world usage...


## When to Use This vs Impact-Analysis

| Scenario | Use app-summary | Use impact-analysis |
|----------|-----------------|-------------------|
| Planning a major architectural change | ✅ Yes | ❌ No (new objects don't exist) |
| Understanding system structure | ✅ Yes | ❌ No (too broad) |
| Scoping migration effort | ✅ Yes | ❌ No (new objects don't exist) |
| Making a change to an existing object | ❌ Maybe later | ✅ Yes |
| Estimating affected systems | ✅ Yes (planning) | ✅ Yes (specific change) |
| Architectural discussions with AI | ✅ Yes | ❌ No (too specific) |


## Next Steps

1. Generate your app-summary: `knack-sleuth app-summary --app-id YOUR_APP_ID --format json`
2. Open a conversation with an AI agent
3. Paste your architecture + the conversation starter prompt
4. Walk through your conversion plan together
5. Save the conversation as your project documentation
6. Share your findings with GH Issue (for now)


## Related Documentation

- [App Summary Documentation](./APP_SUMMARY.md) - Detailed explanation of all metrics
- [Concepts & Terminology](../README.md#concepts--terminology) - Understanding the metrics

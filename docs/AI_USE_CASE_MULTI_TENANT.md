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

The AI now has complete architectural context and can help you reason through:

#### Example Conversation Flow

**You:** 
"I'm thinking of creating an `Organization` object to represent each tenant. Each org would have a billing contact, configuration settings, and will be the parent for scoping."

**AI:** *(analyzes your app_architecture.json)*
"Based on your architecture, I see you have 34 objects total, with 3 core entities (Users, Orders, Products). Creating an Organization object is a good approach. However, I notice you have complex relationships:
- Users has 12 inbound connections from various objects
- Orders is a hub with 18 total connections
- You have 8 bottleneck objects with high fan-out

This means you'll need to carefully add organization scoping to avoid breaking these relationships. Which objects do you think should be organization-scoped vs shared?"

**You:**
"I think Users should be organization-scoped - each org has their own users. But Products should be shared across all orgs."

**AI:**
"That's workable, but I see you have formula fields and views that reference Users in 14 different places. Let me check the dependency... You have a 'Product Recommendations' calculation that depends on User data. If Users are org-scoped but Products are shared, that calculation will break. Here are your options:
1. Make Products org-scoped too
2. Rethink the recommendation logic to work across orgs
3. Create a denormalized cross-org user summary

Each has different complexity. The impact-analysis tool could help later, but for now let's talk about which fits your business model..."

## Sample Architecture Context

When you paste your app_architecture.json, the AI has access to:

```json
{
  "application": {
    "name": "SaaS Platform",
    "id": "app_123",
    "complexity_metrics": {
      "total_objects": 34,
      "total_fields": 287,
      "total_scenes": 45,
      "total_views": 89,
      "total_records": 125000,
      "connection_density": 0.18
    }
  },
  "domain_model": {
    "core_entities": [
      {
        "name": "Users",
        "object_key": "object_1",
        "record_count": 5200,
        "total_connections": 12,
        "centrality_score": 0.85,
        "importance_score": 0.92,
        "primary_role": "transactional"
      },
      // ... more core entities
    ],
    "transactional_entities": [/* 18 objects */],
    "reference_data": [/* 8 objects */],
    "supporting_entities": [/* 7 objects */]
  },
  "relationship_map": {
    "connection_graph": {
      "total_connections": 47
    },
    "hub_objects": [
      {
        "object": "Orders",
        "total_connections": 18,
        "inbound_connections": 12,
        "outbound_connections": 6,
        "interpretation": "Core hub - high bidirectional connectivity"
      }
      // ... more hubs
    ],
    "dependency_clusters": [/* 3 clusters */]
  },
  "technical_debt_indicators": {
    "bottleneck_objects": 8,
    "orphaned_fields": 12,
    "tight_coupling_pairs": 5
  },
  "extensibility_assessment": {
    "modularity_score": 0.64,
    "architectural_style": "modular"
  }
}
```

## AI Can Help You With

### 1. **Scoping Analysis**
"Based on your hub objects and dependency clusters, here's what I think needs org-scoping..."

### 2. **Risk Assessment**
"You have 8 bottleneck objects - these are high-risk. Converting them to multi-tenant will require careful planning..."

### 3. **Complexity Estimation**
"Given your connection density and 34 objects, I estimate 60-80% need some modification. Your 5 tight coupling pairs will be the trickiest..."

### 4. **Migration Strategy**
"Your clusters suggest this migration approach:
- Phase 1: Scope the 'User Management' cluster (objects A, B, C) - low external dependencies
- Phase 2: Scope 'Order Processing' cluster - trickier due to hub objects
- Phase 3: Handle shared reference data..."

### 5. **Data Migration Planning**
"You have 125,000 total records. Based on your object distribution, here's my estimate of what needs remapping..."

## Benefits of This Approach

✅ **Comprehensive Context** - AI understands your complete architecture, not just one piece  
✅ **Pattern Recognition** - AI spots risky patterns (tight coupling, bottlenecks) you might miss  
✅ **Collaborative** - You drive the conversation; AI provides analysis and alternatives  
✅ **Before-the-fact** - Plan architectural changes before building them  
✅ **Estimation Ready** - AI can provide effort estimates based on architectural complexity  
✅ **Documentation** - Save the conversation as your implementation plan  

## When to Use This vs Impact-Analysis

| Scenario | Use app-summary | Use impact-analysis |
|----------|-----------------|-------------------|
| Planning a major architectural change | ✅ Yes | ❌ No (new objects don't exist) |
| Understanding system structure | ✅ Yes | ❌ No (too broad) |
| Scoping migration effort | ✅ Yes | ❌ No (new objects don't exist) |
| Making a change to an existing object | ❌ Maybe later | ✅ Yes |
| Estimating affected systems | ✅ Yes (planning) | ✅ Yes (specific change) |
| Architectural discussions with AI | ✅ Yes | ❌ No (too specific) |

## Best Practices

1. **Start Broad** - Begin with high-level architectural questions
2. **Use Metrics** - Reference specific metrics when discussing decisions
3. **Ask for Alternatives** - "What are the tradeoffs between these approaches?"
4. **Document Decisions** - Save the conversation and your reasoning
5. **Validate Assumptions** - "Does this match what you see in the architecture?"
6. **Plan Phases** - Let AI help break the work into milestones
7. **Consider Clusters** - Use dependency clusters to identify natural boundaries

## Example Questions to Ask

- "What's the highest-risk part of this conversion?"
- "Which core entities will be hardest to convert?"
- "How should I handle the tight coupling pairs?"
- "What's my estimated effort: 40 hours? 100 hours? 200 hours?"
- "Should I convert all objects at once or phase it in?"
- "Which objects can stay organization-agnostic?"
- "What new tables/fields do I need to add for tenancy?"
- "How should I handle reference data that's shared vs org-specific?"

## Next Steps

1. Generate your app-summary: `knack-sleuth app-summary --app-id YOUR_APP_ID --format json`
2. Open a conversation with an AI agent
3. Paste your architecture + the conversation starter prompt
4. Walk through your conversion plan together
5. Save the conversation as your project documentation

## Related Documentation

- [App Summary Documentation](./APP_SUMMARY.md) - Detailed explanation of all metrics
- [Concepts & Terminology](../README.md#concepts--terminology) - Understanding the metrics
